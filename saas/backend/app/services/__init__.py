"""
Purpose: Group the backend services for Tesla access, storage, e-mail and sync orchestration.
Input/Output: Other modules import concrete service classes from this package.
Invariants: Each service has one main responsibility to keep failures easier to isolate.
Debug: If behavior differs across API and worker, compare which service implementation each one instantiates.
"""

