name: Pull Request
description: Describe your change to Söyle
labels: []
body:
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: What does this PR do and why?
    validations:
      required: true
  - type: checkboxes
    id: checks
    attributes:
      label: Checks
      options:
        - label: "`uv run pytest` passes locally"
          required: true
        - label: "`uv run ruff check .` is clean"
          required: true
        - label: "CHANGELOG.md updated (if user-facing)"
          required: false
        - label: "Docs updated if behavior changed"
          required: false
  - type: textarea
    id: notes
    attributes:
      label: Notes for reviewers
      description: Anything reviewers should know (risks, manual test steps).
    validations:
      required: false
