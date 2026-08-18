# -*- coding: utf-8 -*-
from odoo import fields, models


class CrPayrollIncident(models.Model):
    _inherit = "cr.payroll.incident"

    incident_type = fields.Selection(
        selection_add=[
            ("productivity", "Productividad"),
            ("availability", "Disponibilidad / guardia"),
            ("unpaid_hours", "Horas no laboradas"),
            ("unpaid_days", "Días no laborados"),
            ("tardiness", "Tardía"),
            ("salary_difference", "Diferencia salarial"),
            ("vacation_pay", "Pago de vacaciones"),
            ("ccss_disability", "Pago incapacidad CCSS"),
            ("ins_disability", "Pago incapacidad INS"),
            ("maternity", "Pago maternidad"),
            ("paternity", "Pago paternidad"),
        ],
        ondelete={
            "productivity": "cascade",
            "availability": "cascade",
            "unpaid_hours": "cascade",
            "unpaid_days": "cascade",
            "tardiness": "cascade",
            "salary_difference": "cascade",
            "vacation_pay": "cascade",
            "ccss_disability": "cascade",
            "ins_disability": "cascade",
            "maternity": "cascade",
            "paternity": "cascade",
        },
    )
    cr_origin_model = fields.Char(string="Modelo origen", index=True, copy=False)
    cr_origin_id = fields.Integer(string="ID origen", index=True, copy=False)
    cr_origin_period = fields.Char(string="Período origen", copy=False)
    cr_approved_by_id = fields.Many2one("res.users", string="Aprobado por", readonly=True, copy=False)
    cr_approved_at = fields.Datetime(string="Fecha aprobación", readonly=True, copy=False)

    def action_approve(self):
        result = super().action_approve()
        self.write({
            "cr_approved_by_id": self.env.user.id,
            "cr_approved_at": fields.Datetime.now(),
        })
        return result
