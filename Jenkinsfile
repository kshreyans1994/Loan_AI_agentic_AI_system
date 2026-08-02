/*
 * CI pipeline for LoanIQ.
 *
 * Jenkins' job stops at "push a new image and record its tag in the
 * GitOps manifest repo." It deliberately does NOT run kubectl/helm
 * against the cluster — that's ArgoCD's job, watching the manifest repo
 * and reconciling the cluster to match. This separation is the whole
 * point of the Jenkins+ArgoCD pattern: Jenkins owns "is this code good
 * and buildable," ArgoCD owns "does the cluster match what Git says it
 * should be." Mixing the two (Jenkins doing `kubectl apply`) defeats
 * GitOps — you'd have two different systems able to change cluster
 * state, with no single source of truth to diff against or roll back to.
 *
 * See docs/DEPLOYMENT.md for the full pipeline diagram and rationale.
 */

pipeline {
    agent any

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        ansiColor('xterm')
    }

    environment {
        // Container registry this project's images are pushed to.
        REGISTRY        = 'ghcr.io/your-org/loaniq'
        IMAGE_TAG       = "${env.GIT_COMMIT.take(8)}"
        FULL_IMAGE      = "${REGISTRY}:${IMAGE_TAG}"

        // Separate repo ArgoCD actually watches — see deploy/ in THIS
        // repo for the manifest templates; the manifest repo is where
        // the rendered, environment-specific versions live.
        MANIFEST_REPO   = 'git@github.com:your-org/loaniq-gitops.git'
        MANIFEST_BRANCH = 'main'

        // Credentials IDs configured in Jenkins (not secret values —
        // Jenkins resolves these from its own credential store).
        REGISTRY_CREDS  = 'ghcr-credentials'
        GITOPS_SSH_CRED = 'gitops-deploy-key'
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --quiet ruff
                    ruff check app/ tests/
                '''
            }
        }

        stage('Unit Tests') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pip install --quiet -r requirements.txt
                    pytest tests/ -v --junitxml=test-results.xml
                '''
            }
            post {
                always {
                    junit 'test-results.xml'
                }
            }
        }

        stage('Build Image') {
            steps {
                sh "docker build -t ${FULL_IMAGE} -t ${REGISTRY}:latest ."
            }
        }

        stage('Scan Image') {
            steps {
                // Fails the build on HIGH/CRITICAL CVEs. Adjust --exit-code
                // to 0 if you want scan results without blocking the pipeline
                // while the project is still POC-stage.
                sh """
                    trivy image --severity HIGH,CRITICAL --exit-code 1 ${FULL_IMAGE}
                """
            }
        }

        stage('Push Image') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: env.REGISTRY_CREDS,
                    usernameVariable: 'REG_USER',
                    passwordVariable: 'REG_PASS'
                )]) {
                    sh '''
                        echo "$REG_PASS" | docker login ghcr.io -u "$REG_USER" --password-stdin
                        docker push ${FULL_IMAGE}
                        docker push ${REGISTRY}:latest
                    '''
                }
            }
        }

        stage('Update GitOps Manifest') {
            steps {
                sshagent(credentials: [env.GITOPS_SSH_CRED]) {
                    sh '''
                        rm -rf gitops-checkout
                        git clone --branch ${MANIFEST_BRANCH} ${MANIFEST_REPO} gitops-checkout
                        cd gitops-checkout

                        # Bump the image tag for the environment this build targets.
                        # kustomize edit is the standard, diff-friendly way to do this
                        # rather than sed — see deploy/overlays/staging/kustomization.yaml
                        cd overlays/staging
                        kustomize edit set image loaniq=${FULL_IMAGE}
                        cd ../..

                        git config user.email "jenkins@your-org.com"
                        git config user.name "Jenkins CI"
                        git add -A
                        git commit -m "loaniq: deploy ${IMAGE_TAG} to staging (build ${BUILD_NUMBER})"
                        git push origin ${MANIFEST_BRANCH}
                    '''
                }
            }
        }
    }

    post {
        success {
            echo "Image ${FULL_IMAGE} pushed and staging manifest updated. ArgoCD will reconcile automatically within its poll interval (or immediately if webhook-triggered)."
        }
        failure {
            echo "Pipeline failed — no manifest update was pushed, so ArgoCD has nothing new to sync. Cluster state is unaffected by this failed run."
        }
    }
}
