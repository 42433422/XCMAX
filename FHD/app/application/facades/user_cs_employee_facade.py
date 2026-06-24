# -*- coding: utf-8 -*-
"""Application-layer facade for the user-facing CS employee runner.

Routes import the dedicated-CS employee runner through the application layer,
not directly from ``app.services.*`` — see the ``routes->services`` rule in
``FHD/scripts/arch_fitness.py``. This is a thin re-export; the implementation
stays in ``app.services.user_cs_employee_runner``.
"""

from app.services.user_cs_employee_runner import EMPLOYEE_MOD_ID, run_user_cs_employee

__all__ = ["EMPLOYEE_MOD_ID", "run_user_cs_employee"]
