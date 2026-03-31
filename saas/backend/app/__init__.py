"""
Purpose: Mark `app` as the backend package for API, worker and shared services.
Input/Output: Python imports modules from this package at runtime.
Invariants: Shared logic lives here so API and worker stay aligned.
Debug: If imports fail, verify that Docker copied the `app` directory into `/app/app`.
"""

