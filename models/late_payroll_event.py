# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrPayrollLateEvent(models.Model):
    _name = "cr.payroll.late.event"
    _description = "Evento tardío de nómina Costa Rica"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "registered_date desc, id desc"

    name = fields.Char(required=True, default="Evento tardío", tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, index=True, tracking=True)
    contract_id = fields.Many2one("hr.contract", domain="[('employee_id','=',employee_id)]")
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    event_type = fields.Selection([
        ("CCSS", "Incapacidad CCSS"),
        ("INS", "Incapacidad INS"),
        ("MATERNITY", "Licencia de maternidad"),
        ("PATERNITY", "Licencia de paternidad"),
    ], required=True, tracking=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    registered_date = fields.Date(required=True, default=fields.Date.context_today)
    adjustment_date = fields.Date(string="Fecha de ajuste en nómina", default=fields.Date.context_today)
    document_number = fields.Char(string="Número de documento", required=True, index=True, tracking=True)
    attachment_ids = fields.Many2many("ir.attachment", string="Documento / evidencia")
    leave_type_id = fields.Many2one("hr.leave.type", string="Tipo de ausencia")
    generated_leave_id = fields.Many2one("hr.leave", readonly=True, copy=False)
    restored_vacation_days = fields.Float(string="Vacaciones restituidas", readonly=True, copy=False)
    affected_closed_payslip_ids = fields.Many2many("hr.payslip", string="Recibos cerrados afectados", readonly=True)
    notes = fields.Text()
    state = fields.Selection([
        ("draft", "Borrador"),
        ("review", "En revisión"),
        ("applied", "Aplicado"),
        ("cancel", "Cancelado"),
    ], default="draft", tracking=True)

    _sql_constraints = [
        ("document_number_unique", "unique(document_number, company_id)", "El número de documento ya fue registrado para esta compañía."),
    ]

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise ValidationError(_("La fecha final no puede ser anterior a la inicial."))

    def _find_leave_type(self):
        self.ensure_one()
        if self.leave_type_id:
            return self.leave_type_id
        rule = self.env["cr.payroll.disability.rule"].sudo().search([
            ("code", "=", self.event_type),
            ("active", "=", True),
            ("date_from", "<=", self.date_from),
            "|", ("date_to", "=", False), ("date_to", ">=", self.date_from),
            "|", ("company_id", "=", self.company_id.id), ("company_id", "=", False),
        ], order="company_id desc,date_from desc", limit=1)
        if not rule or not rule.leave_type_id:
            raise ValidationError(_("No existe una regla de incapacidad con tipo de ausencia configurado para %s.") % self.event_type)
        return rule.leave_type_id

    def action_review(self):
        for rec in self:
            if not rec.attachment_ids:
                raise ValidationError(_("Debe adjuntar el documento que respalda el evento tardío."))
            rec.state = "review"
        return True

    def action_apply(self):
        Leave = self.env["hr.leave"].sudo()
        for rec in self:
            if rec.state != "review":
                raise ValidationError(_("El evento debe estar en revisión antes de aplicarlo."))
            leave_type = rec._find_leave_type()

            # Rechaza ausencias aprobadas que se superponen. Si eran vacaciones,
            # Odoo devuelve automáticamente esos días a la asignación nativa.
            overlaps = Leave.search([
                ("employee_id", "=", rec.employee_id.id),
                ("id", "!=", rec.generated_leave_id.id or 0),
                ("state", "in", ["confirm", "validate1", "validate"]),
                ("request_date_to", ">=", rec.date_from),
                ("request_date_from", "<=", rec.date_to),
            ])
            restored = 0.0
            for leave in overlaps:
                if (leave.holiday_status_id.name or "").strip() == "CR - Vacaciones":
                    restored += leave.number_of_days or 0.0
                if hasattr(leave, "action_refuse"):
                    leave.action_refuse()

            vals = {
                "name": "%s - %s" % (rec.name, rec.document_number),
                "employee_id": rec.employee_id.id,
                "holiday_status_id": leave_type.id,
                "request_date_from": rec.date_from,
                "request_date_to": rec.date_to,
            }
            generated = Leave.create(vals)
            # Se intenta aprobar con el flujo nativo. Si el tipo exige doble
            # aprobación, la segunda validación queda registrada igualmente.
            if hasattr(generated, "action_approve") and generated.state == "confirm":
                generated.action_approve()
            if hasattr(generated, "action_validate") and generated.state in ("confirm", "validate1"):
                generated.action_validate()

            closed = self.env["hr.payslip"].sudo().search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "in", ["done", "paid"]),
                ("date_to", ">=", rec.date_from),
                ("date_from", "<=", rec.date_to),
            ])
            rec.write({
                "leave_type_id": leave_type.id,
                "generated_leave_id": generated.id,
                "restored_vacation_days": restored,
                "affected_closed_payslip_ids": [(6, 0, closed.ids)],
                "state": "applied",
            })
        return True
