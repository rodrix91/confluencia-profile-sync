# Confluencia · public profile metadata

Bounded, read-only checks of the official public GitHub, GitLab and Hugging Face APIs. This repository contains only new updater code and allowlisted public reference metadata. It contains no CV documents, private evidence, photographs, contact details, credentials or history from the website's working repository.

The observation is metadata, not proof of software execution, exclusive authorship, delivered projects, publications or client outcomes. Source types retain their review date. No model, Space, notebook or external repository code is executed. Kaggle notebook totals remain unknown; LinkedIn and X have no scraping or feed here.

## Operation

The workflow runs daily at **10:37 UTC / 06:37 America/La_Paz**, on explicit manual dispatch, or after changes to updater code/policy. GitHub schedules are best effort. State-only commits do not trigger another run. Concurrent runs are serialized; a conflicting write fails instead of overwriting a newer remote state.

Only standard Ubuntu runners in this public repository are allowed. They are free under GitHub's public-repository Actions terms; private copies are skipped by the job guard. No larger runners, inference services, paid subscriptions, artifact storage, Actions cache or third-party API keys are required. The job has a six-minute ceiling; the reader is bounded to 24 public requests, four pages per collection, 2 MB per response and eight seconds per read.

`approved/references.json` defines reviewed identities and source types. `state/current.json` atomically holds the public cache, last accepted observation and latest run status. Only this state file is written by the ephemeral repository-scoped job token. No token is stored in a file or Git configuration. Official actions are pinned to verified commit SHAs.

Failures, missing records, renamed identities and unknown IDs retain the accepted observation. Unreviewed names/URLs are excluded from persisted state, with a review count/status. The updater's own repository is explicitly excluded from professional-reference totals using GitHub's runtime repository ID. A failed final readiness check marks the workflow failed after safe state/backoff has been persisted. A persistence timeout requires readback; it is not assumed that a remote write never happened.

Inspect the last run in Actions and the `lastRun` field. `promoted` means the approved metadata was checked; `retained` means the previous accepted observation remains. A seed is dated input, not an executed remote job. Disabling the workflow in Actions pauses scheduling without losing state. Changing repository visibility to private also prevents allocating a runner under this workflow.

## Updating reviewed references

Review identity, public namespace, URL and type before editing policy. Never update hashes or add an identity only to silence a failure. Preserve existing reference IDs. The website's editorial CV, case studies and academic records are maintained separately. Publishing an observation here does not deploy or modify that website; its controlled import/deployment is verified separately.

Run offline contracts with `python scripts/profile-job.test.py -v`. Dependencies are Python's standard library. The live read is `python scripts/profile-job.py`; it writes a safe bundle even when source checks require review. `python scripts/profile-job.py --assert-ready` exits 2 when the observation was retained. Persistence is reserved for the GitHub runtime; don't paste credentials into commands.

## Español

Actualización acotada de metadatos públicos de GitHub, GitLab y Hugging Face. El repositorio excluye los documentos del CV, evidencia privada, fotografías, datos de contacto e historial del proyecto original. Los tipos conservan la fecha de revisión: no acreditan ejecución, autoría exclusiva o resultados.

Consulta diaria a las **06:37 de Bolivia**, con control manual desde Actions. Los fallos mantienen la última observación válida; los registros nuevos o modificados requieren revisión. Solo se usa el ejecutor Ubuntu estándar de este repositorio público. No se crean artefactos/cachés de Actions ni se necesitan claves externas. La publicación de estos metadatos no despliega la web personal.

Para pausar, desactiva el workflow desde Actions. Para ampliar el conjunto, revisa identidad/tipo y modifica únicamente la política pertinente; no borres registros o cambies hashes para ocultar una discrepancia.

References: [official API practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api), [workflow scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule), [public-runner billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [GitLab API](https://docs.gitlab.com/api/projects/), [Hugging Face API](https://huggingface.co/docs/hub/api).
