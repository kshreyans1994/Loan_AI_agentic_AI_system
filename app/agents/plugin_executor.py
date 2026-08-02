"""Plugin execution node — runs every plugin app.agents.supervisor
selected for this turn (state.selected_plugins), in order, chaining
application updates between them so a later plugin in the same turn
sees data an earlier one just set (e.g. an eligibility check right
after a document upload in the same message).

Also responsible for patching state.application when a plugin surfaces
data the application should remember going forward (e.g. an income
figure extracted from a document, or an income signal from an external
bank/financial-statement analyzer). Plugins signal this via an
`application_updates` dict in their PluginResult.data rather than
mutating state directly — keeps plugins pure functions of their inputs,
and keeps "what actually changes application state" auditable in one
place (here) instead of scattered across every plugin.
"""
from __future__ import annotations

from app.core.schemas import AgentState, DocumentType, Intent, PluginResult
from app.plugins.registry import OFFER_PLUGIN, get_plugin_for_intent

# Maps a validated document's extracted field name -> LoanApplication
# field name, for the subset of fields we want auto-applied after a
# successful document verification. Extend this as new document types
# gain fields worth promoting onto the application automatically.
_DOCUMENT_FIELD_TO_APPLICATION_FIELD = {
    DocumentType.SALARY_SLIP: {"net_pay": "monthly_income", "monthly_income": "monthly_income"},
    DocumentType.PAN: {"pan_number": "pan_number"},
    DocumentType.AADHAAR: {"aadhaar_number": "aadhaar_number", "name": "applicant_name"},
}


def _application_updates_from_document(application, result_data: dict) -> dict:
    """Salary-slip OCR is the lowest-precedence income signal (see
    external_analyzer_ingest.py's INCOME_SOURCE_PRECEDENCE) — only apply
    it if no higher-precedence source has already set monthly_income."""
    try:
        doc_type = DocumentType(result_data.get("doc_type"))
    except ValueError:
        return {}

    field_map = _DOCUMENT_FIELD_TO_APPLICATION_FIELD.get(doc_type, {})
    if not field_map:
        return {}

    extracted = {f["name"]: f["value"] for f in result_data.get("fields", [])}
    updates: dict = {}

    for doc_field, app_field in field_map.items():
        if doc_field not in extracted:
            continue
        value = extracted[doc_field]
        if app_field == "monthly_income":
            if application.income_signal_source is not None:
                continue  # a higher-precedence source already set this
            try:
                updates["monthly_income"] = float(str(value).replace(",", ""))
                updates["income_signal_source"] = "salary_slip_ocr"
            except ValueError:
                continue
        else:
            updates[app_field] = value

    return updates


def _apply_updates(application, updates: dict):
    return application.model_copy(update=updates)


def _run_one_plugin(intent: Intent, application, pending_action) -> tuple[PluginResult | None, object]:
    """Runs a single selected plugin, returns (result_or_None, possibly-updated application).
    Isolated from the loop below so it's independently testable and so
    the offer-recommendation chain reads clearly as "one plugin, then a
    conditional follow-up" rather than being buried in loop state."""
    plugin = get_plugin_for_intent(intent)
    if plugin is None:
        return None, application

    kwargs = {}
    if intent == Intent.UPLOAD_DOCUMENT:
        kwargs["image_bytes"] = pending_action
    elif intent == Intent.SUBMIT_BANK_STATEMENT_ANALYSIS:
        kwargs["analyzer_type"] = "bank_statement"
        kwargs["payload"] = pending_action
    elif intent == Intent.SUBMIT_FINANCIAL_STATEMENT_ANALYSIS:
        kwargs["analyzer_type"] = "financial_statement"
        kwargs["payload"] = pending_action

    result = plugin.run(application, **kwargs)

    if result.success and "application_updates" in result.data:
        application = _apply_updates(application, result.data["application_updates"])
    elif result.success and intent == Intent.UPLOAD_DOCUMENT:
        doc_updates = _application_updates_from_document(application, result.data)
        if doc_updates:
            application = _apply_updates(application, doc_updates)

    return result, application


def execute_plugins(state: AgentState) -> dict:
    if not state.selected_plugins:
        return {}

    results = list(state.plugin_results)
    application = state.application

    for intent in state.selected_plugins:
        result, application = _run_one_plugin(intent, application, state.pending_action)
        if result is None:
            continue
        results.append(result)

        # Chain: a passing eligibility check triggers offer recommendation,
        # mirroring the diagram's "Offer & Recommendation" plugin feeding
        # off eligibility output rather than being independently triggered.
        if intent == Intent.CHECK_ELIGIBILITY and result.success and result.data.get("eligible"):
            offer_result = OFFER_PLUGIN.run(application)
            results.append(offer_result)

    return {"plugin_results": results, "application": application}
