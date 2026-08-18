# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrPayrollRetroactiveAdjustment(models.Model):
    _name = "cr.payroll.retroactive.adjustment"
    _description = "Ajuste retroactivo de nómina Costa Rica"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "target_date desc, id desc"

    name = fields.Char(required=True, default="Ajuste retroactivo", tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, index=True, tracking=True)
    contract_id = fields.Many2one("hr.contract", required=True, domain="[('employee_id', '=', employee_id)]")
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    origin_date_from = fields.Date(string="Desde período origen", required=True)
    origin_date_to = fields.Date(string="Hasta período origen", required=True)
    target_date = fields.Date(string="Fecha de nómina complementaria", required=True, default=fields.Date.context_today)
    old_wage = fields.Monetary(string="Salario anterior", required=True, currency_field="currency_id")
    new_wage = fields.Monetary(string="Salario nuevo", required=True, currency_field="currency_id")
    reason = fields.Text(string="Motivo", required=True)
    attachment_ids = fields.Many2many("ir.attachment", string="Evidencia")
    line_ids = fields.One2many("cr.payroll.retroactive.adjustment.line", "adjustment_id", string="Diferencias")
    amount_total = fields.Monetary(compute="_compute_total", store=True, currency_field="currency_id")
    state = fields.Selection([
        ("draft", "Borrador"),
        ("calculated", "Calculado"),
        ("approved", "Aprobado"),
        ("generated", "Complementaria generada"),
        ("cancel", "Cancelado"),
    ], default="draft", required=True, tracking=True)
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    incident_ids = fields.Many2many(
        "cr.payroll.incident",
        string="Incidencias generadas",
        compute="_compute_incident_ids",
        readonly=True,
    )

    def _compute_incident_ids(self):
        Incident = self.env["cr.payroll.incident"].sudo()
        for rec in self:
            rec.incident_ids = Incident.search([
                ("cr_origin_model", "=", rec._name),
                ("cr_origin_id", "=", rec.id),
            ])

    @api.depends("line_ids.difference")
    def _compute_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("difference"))

    @api.constrains("origin_date_from", "origin_date_to", "old_wage", "new_wage")
    def _check_values(self):
        for rec in self:
            if rec.origin_date_to < rec.origin_date_from:
                raise ValidationError(_("El período origen es inválido."))
            if rec.old_wage <= 0 or rec.new_wage <= 0:
                raise ValidationError(_("Los salarios deben ser mayores que cero."))

    def action_calculate(self):
        Line = self.env["cr.payroll.retroactive.adjustment.line"].sudo()
        for rec in self:
            rec.line_ids.unlink()
            slips = self.env["hr.payslip"].sudo().search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "in", ["done", "paid"]),
                ("date_to", ">=", rec.origin_date_from),
                ("date_from", "<=", rec.origin_date_to),
            ], order="date_from,id")
            if not slips:
                raise ValidationError(_("No existen recibos cerrados en el período origen."))

            ratio = rec.new_wage / rec.old_wage
            wage_sensitive_codes = {
                "BASIC", "CR_BASIC", "CR_BASIC_BIWEEKLY", "CR_BASIC_WEEKLY", "CR_BASIC_HOURLY",
                "CR_OT_15", "CR_OT_20", "CR_OT_30",
            }
            wage_sensitive_categories = {"BASIC", "OVERTIME", "ALLOWANCE"}
            fixed_variable_codes = {"CR_COMMISSION", "CR_BONUS", "CR_INCENTIVE", "CR_PRODUCTIVITY", "CR_AVAILABILITY", "CR_REIMBURSEMENT", "CR_OTHER_INCOME"}
            for slip in slips:
                for line in slip.line_ids.filtered(lambda l: l.total and l.total > 0):
                    code = (line.code or "").upper()
                    category = (line.category_id.code or "").upper()
                    # No se recalculan importes fijos/no salariales por inferencia.
                    # Solo conceptos inequívocamente dependientes del salario.
                    if code in fixed_variable_codes:
                        continue
                    if code not in wage_sensitive_codes and category not in wage_sensitive_categories:
                        continue
                    recalculated = line.total * ratio
                    difference = recalculated - line.total
                    if abs(difference) < 0.005:
                        continue
                    Line.create({
                        "adjustment_id": rec.id,
                        "payslip_id": slip.id,
                        "origin_date_from": slip.date_from,
                        "origin_date_to": slip.date_to,
                        "salary_rule_code": line.code,
                        "concept_name": line.name,
                        "original_amount": line.total,
                        "recalculated_amount": recalculated,
                        "difference": difference,
                        "include": True,
                    })
            rec.state = "calculated"
        return True

    def action_approve(self):
        for rec in self:
            if not rec.line_ids.filtered("include"):
                raise ValidationError(_("No hay diferencias seleccionadas para aprobar."))
            if not rec.reason:
                raise ValidationError(_("Debe indicar el motivo del retroactivo."))
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
        return True

    def action_generate_complementary(self):
        Incident = self.env["cr.payroll.incident"].sudo()
        for rec in self:
            if rec.state != "approved":
                raise ValidationError(_("El ajuste debe estar aprobado antes de generar la complementaria."))
            existing = Incident.search([
                ("cr_origin_model", "=", rec._name),
                ("cr_origin_id", "=", rec.id),
                ("state", "not in", ["cancel", "rejected"]),
            ])
            if existing:
                raise ValidationError(_("Ya existen incidencias activas generadas para este retroactivo."))
            for line in rec.line_ids.filtered(lambda l: l.include and l.difference > 0):
                Incident.create({
                    "name": "Retroactivo %s - %s" % (line.concept_name, line.origin_period),
                    "employee_id": rec.employee_id.id,
                    "contract_id": rec.contract_id.id,
                    "date": rec.target_date,
                    "incident_type": "retroactive",
                    "quantity": 1.0,
                    "rate": line.difference,
                    "amount": line.difference,
                    "description": "%s\nPeríodo origen: %s\nRegla: %s" % (rec.reason, line.origin_period, line.salary_rule_code or "-"),
                    "state": "approved",
                    "cr_origin_model": rec._name,
                    "cr_origin_id": rec.id,
                    "cr_origin_period": line.origin_period,
                    "cr_approved_by_id": rec.approved_by_id.id,
                    "cr_approved_at": rec.approved_at,
                })
            rec.state = "generated"
        return True


class CrPayrollRetroactiveAdjustmentLine(models.Model):
    _name = "cr.payroll.retroactive.adjustment.line"
    _description = "Línea de ajuste retroactivo CR"
    _order = "origin_date_from, id"

    adjustment_id = fields.Many2one("cr.payroll.retroactive.adjustment", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="adjustment_id.currency_id")
    payslip_id = fields.Many2one("hr.payslip", string="Recibo original", required=True, readonly=True)
    origin_date_from = fields.Date(readonly=True)
    origin_date_to = fields.Date(readonly=True)
    origin_period = fields.Char(compute="_compute_origin_period", store=True)
    salary_rule_code = fields.Char(string="Código regla", readonly=True)
    concept_name = fields.Char(string="Concepto", readonly=True)
    original_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    recalculated_amount = fields.Monetary(currency_field="currency_id")
    difference = fields.Monetary(currency_field="currency_id", compute="_compute_difference", store=True)
    include = fields.Boolean(default=True)
    notes = fields.Char()

    @api.depends("origin_date_from", "origin_date_to")
    def _compute_origin_period(self):
        for line in self:
            if line.origin_date_from and line.origin_date_to:
                line.origin_period = "%s a %s" % (line.origin_date_from, line.origin_date_to)
            else:
                line.origin_period = ""

    @api.depends("original_amount", "recalculated_amount")
    def _compute_difference(self):
        for line in self:
            line.difference = line.recalculated_amount - line.original_amount
