# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


REFERENCE_COMPONENTS = [
    ("pending_salary", "Salario pendiente"),
    ("pending_commissions", "Comisiones"),
    ("pending_overtime", "Horas extra"),
    ("vacation_amount", "Vacaciones"),
    ("aguinaldo_amount", "Aguinaldo proporcional"),
    ("notice_amount", "Preaviso"),
    ("severance_amount", "Cesantía"),
    ("other_income", "Otros ingresos"),
    ("deductions", "Deducciones"),
]


class CrPayrollTermination(models.Model):
    _inherit = "cr.payroll.termination"

    reference_locked = fields.Boolean(string="Referencia legal congelada", readonly=True, copy=False)
    reference_locked_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    reference_locked_at = fields.Datetime(readonly=True, copy=False)
    agreement_line_ids = fields.One2many("cr.payroll.termination.agreement.line", "termination_id", string="Acuerdo negociado")
    agreement_attachment_ids = fields.Many2many("ir.attachment", "cr_term_agreement_attachment_rel", "termination_id", "attachment_id", string="Acuerdo firmado")
    agreement_state = fields.Selection([
        ("none", "Sin acuerdo"),
        ("draft", "Borrador"),
        ("approved", "Aprobado"),
        ("reversed", "Revertido"),
    ], default="none", string="Estado acuerdo")
    agreement_approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    agreement_approved_at = fields.Datetime(readonly=True, copy=False)
    agreement_total = fields.Monetary(compute="_compute_agreement_totals", currency_field="currency_id")
    agreement_difference = fields.Monetary(compute="_compute_agreement_totals", currency_field="currency_id")
    loan_balance_before = fields.Monetary(string="Saldo préstamo antes", currency_field="currency_id")
    loan_deduction_agreed = fields.Monetary(string="Préstamo a deducir", currency_field="currency_id")
    loan_residual_receivable = fields.Monetary(compute="_compute_agreement_totals", string="Saldo residual CxC", currency_field="currency_id")
    residual_receivable_move_id = fields.Many2one("account.move", readonly=True, copy=False)

    @api.depends("agreement_line_ids.agreed_amount", "agreement_line_ids.reference_amount", "loan_balance_before", "loan_deduction_agreed")
    def _compute_agreement_totals(self):
        for rec in self:
            rec.agreement_total = sum(rec.agreement_line_ids.mapped("agreed_amount"))
            rec.agreement_difference = sum(rec.agreement_line_ids.mapped("difference"))
            rec.loan_residual_receivable = max((rec.loan_balance_before or 0.0) - (rec.loan_deduction_agreed or 0.0), 0.0)

    def action_freeze_legal_reference(self):
        Line = self.env["cr.payroll.termination.agreement.line"].sudo()
        for rec in self:
            if rec.reference_locked:
                continue
            rec.agreement_line_ids.unlink()
            for field_name, label in REFERENCE_COMPONENTS:
                amount = rec[field_name] or 0.0
                # Las deducciones se muestran negativas en el comparativo.
                signed = -amount if field_name == "deductions" else amount
                Line.create({
                    "termination_id": rec.id,
                    "component": field_name,
                    "name": label,
                    "reference_amount": signed,
                    "agreed_amount": signed,
                })
            rec.write({
                "reference_locked": True,
                "reference_locked_by_id": self.env.user.id,
                "reference_locked_at": fields.Datetime.now(),
                "agreement_state": "draft",
            })
        return True

    def action_approve_agreement(self):
        for rec in self:
            if not rec.reference_locked:
                raise ValidationError(_("Primero debe congelar el cálculo legal de referencia."))
            changed = rec.agreement_line_ids.filtered(lambda l: abs(l.difference) > 0.005)
            for line in changed:
                if not line.reason:
                    raise ValidationError(_("Toda diferencia negociada debe indicar un motivo: %s") % line.name)
                if not line.attachment_ids and not rec.agreement_attachment_ids:
                    raise ValidationError(_("Toda diferencia negociada debe tener respaldo documental: %s") % line.name)
            rec.write({
                "agreement_state": "approved",
                "agreement_approved_by_id": self.env.user.id,
                "agreement_approved_at": fields.Datetime.now(),
            })
        return True

    def action_reverse_agreement(self):
        self.write({"agreement_state": "reversed"})
        return True


class CrPayrollTerminationAgreementLine(models.Model):
    _name = "cr.payroll.termination.agreement.line"
    _description = "Diferencia de acuerdo de liquidación CR"
    _order = "id"

    termination_id = fields.Many2one("cr.payroll.termination", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="termination_id.currency_id")
    component = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, readonly=True)
    reference_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    agreed_amount = fields.Monetary(currency_field="currency_id")
    difference = fields.Monetary(compute="_compute_difference", currency_field="currency_id")
    reason = fields.Text(string="Motivo de diferencia")
    attachment_ids = fields.Many2many("ir.attachment", string="Evidencia")
    approved_by_id = fields.Many2one(related="termination_id.agreement_approved_by_id", readonly=True)

    @api.depends("reference_amount", "agreed_amount")
    def _compute_difference(self):
        for rec in self:
            rec.difference = rec.agreed_amount - rec.reference_amount

    def write(self, vals):
        if any(line.termination_id.agreement_state == "approved" for line in self):
            raise ValidationError(_("No se puede modificar un acuerdo aprobado. Debe revertirse formalmente."))
        return super().write(vals)

    def unlink(self):
        if any(line.termination_id.agreement_state == "approved" for line in self):
            raise ValidationError(_("No se puede eliminar una línea de un acuerdo aprobado."))
        return super().unlink()
