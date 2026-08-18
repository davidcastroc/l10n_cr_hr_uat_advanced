# -*- coding: utf-8 -*-
{
    "name": "RH Costa Rica - UAT Avanzado",
    "summary": "Retroactivos, eventos tardíos, liquidación negociada y segmentación avanzada de jornadas para Nómina CR",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Castro Li",
    "website": "https://castrolicr.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_cr_hr",
        "hr_payroll",
        "hr_holidays",
        "hr_attendance",
        "account",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/retroactive_views.xml",
        "views/late_event_views.xml",
        "views/severance_advanced_views.xml",
        "views/shift_segmentation_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
