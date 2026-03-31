"""
Purpose: Group API and page routers for the FastAPI application.
Input/Output: The application imports routers from this package during startup.
Invariants: Route modules stay separated by concern, which keeps the user flow easier to follow.
Debug: If a page or endpoint returns 404 unexpectedly, check whether its router is included in `main.py`.
"""

