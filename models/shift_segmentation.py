# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta
import pytz
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrPayrollShiftAnalysis(models.Model):
    _name = "cr.payroll.shift.analysis"
    _description = "Segmentación avanzada de jornada CR"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, default="Análisis de jornada", tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, tracking=True)
    contract_id = fields.Many2one("hr.contract", required=True, domain="[('employee_id','=',employee_id)]")
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    attendance_id = fields.Many2one("hr.attendance", string="Marcación origen", readonly=True)
    date_start = fields.Datetime(string="Entrada", required=True)
    date_stop = fields.Datetime(string="Salida", required=True)
    break_start = fields.Datetime(string="Inicio pausa no remunerada")
    break_stop = fields.Datetime(string="Fin pausa no remunerada")
    ordinary_paid_hours_limit = fields.Float(string="Límite horas ordinarias pagadas", default=6.0, required=True)
    line_ids = fields.One2many("cr.payroll.shift.analysis.line", "analysis_id", string="Segmentos")
    total_presence_hours = fields.Float(compute="_compute_totals")
    total_paid_hours = fields.Float(compute="_compute_totals")
    total_ordinary_hours = fields.Float(compute="_compute_totals")
    total_overtime_hours = fields.Float(compute="_compute_totals")
    payroll_additional_total = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    state = fields.Selection([
        ("draft", "Borrador"),
        ("calculated", "Calculado"),
        ("approved", "Aprobado"),
        ("generated", "Incidencias generadas"),
        ("cancel", "Cancelado"),
    ], default="draft", tracking=True)
    reason = fields.Text(string="Motivo / observaciones")
    attachment_ids = fields.Many2many("ir.attachment", string="Evidencia")
    approved_by_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.depends("date_start", "date_stop", "line_ids.paid_hours", "line_ids.classification", "line_ids.payroll_additional")
    def _compute_totals(self):
        for rec in self:
            if rec.date_start and rec.date_stop:
                rec.total_presence_hours = max((rec.date_stop - rec.date_start).total_seconds() / 3600.0, 0.0)
            else:
                rec.total_presence_hours = 0.0
            rec.total_paid_hours = sum(rec.line_ids.mapped("paid_hours"))
            rec.total_ordinary_hours = sum(rec.line_ids.filtered(lambda l: l.classification in ("ordinary", "holiday_ordinary")).mapped("paid_hours"))
            rec.total_overtime_hours = sum(rec.line_ids.filtered(lambda l: l.classification in ("overtime", "holiday_overtime")).mapped("paid_hours"))
            rec.payroll_additional_total = sum(rec.line_ids.mapped("payroll_additional"))

    @api.constrains("date_start", "date_stop", "break_start", "break_stop")
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_stop and rec.date_stop <= rec.date_start:
                raise ValidationError(_("La salida debe ser posterior a la entrada."))
            if bool(rec.break_start) != bool(rec.break_stop):
                raise ValidationError(_("Debe indicar inicio y fin de la pausa."))
            if rec.break_start and not (rec.date_start <= rec.break_start < rec.break_stop <= rec.date_stop):
                raise ValidationError(_("La pausa debe estar dentro de la jornada."))

    def _local_tz(self):
        self.ensure_one()
        tz_name = self.employee_id.tz or self.env.user.tz or "America/Costa_Rica"
        return pytz.timezone(tz_name)

    def _to_local(self, value):
        tz = self._local_tz()
        if value.tzinfo:
            return value.astimezone(tz)
        return pytz.UTC.localize(value).astimezone(tz)

    def _is_public_holiday(self, local_dt):
        self.ensure_one()
        tz = self._local_tz()
        day_start_local = tz.localize(datetime.combine(local_dt.date(), time.min))
        day_end_local = day_start_local + timedelta(days=1)
        day_start_utc = day_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        day_end_utc = day_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        domain = [
            ("resource_id", "=", False),
            ("date_from", "<", day_end_utc),
            ("date_to", ">", day_start_utc),
            "|", ("company_id", "=", self.company_id.id), ("company_id", "=", False),
        ]
        Leave = self.env["resource.calendar.leaves"].sudo()
        if "cr_is_public_holiday" in Leave._fields:
            domain.append(("cr_is_public_holiday", "=", True))
        return bool(Leave.search_count(domain))

    def _hour_rate(self):
        self.ensure_one()
        contract = self.contract_id
        if contract.cr_salary_mode == "hourly":
            return contract.wage or 0.0
        divisor = (contract.cr_days_divisor or 30.0) * (contract.cr_hours_per_day or 8.0)
        return (contract.wage or 0.0) / divisor if divisor else 0.0

    def action_calculate(self):
        Line = self.env["cr.payroll.shift.analysis.line"].sudo()
        for rec in self:
            rec.line_ids.unlink()
            start = rec._to_local(rec.date_start)
            stop = rec._to_local(rec.date_stop)
            break_start = rec._to_local(rec.break_start) if rec.break_start else False
            break_stop = rec._to_local(rec.break_stop) if rec.break_stop else False

            # Puntos de corte: entrada, salida, medianoches y bordes de pausa.
            points = {start, stop}
            cursor_date = start.date() + timedelta(days=1)
            while cursor_date <= stop.date():
                points.add(rec._local_tz().localize(datetime.combine(cursor_date, time.min)))
                cursor_date += timedelta(days=1)
            if break_start:
                points.update({break_start, break_stop})
            points = sorted(p for p in points if start <= p <= stop)

            raw = []
            for a, b in zip(points[:-1], points[1:]):
                if b <= a:
                    continue
                is_break = bool(break_start and a >= break_start and b <= break_stop)
                raw.append((a, b, is_break, rec._is_public_holiday(a)))

            ordinary_remaining = rec.ordinary_paid_hours_limit
            rate = rec._hour_rate()
            monthly = rec.contract_id.cr_salary_mode != "hourly"
            for a, b, is_break, is_holiday in raw:
                hours = (b - a).total_seconds() / 3600.0
                if is_break:
                    Line.create({
                        "analysis_id": rec.id,
                        "date_start": a.astimezone(pytz.UTC).replace(tzinfo=None),
                        "date_stop": b.astimezone(pytz.UTC).replace(tzinfo=None),
                        "classification": "break",
                        "presence_hours": hours,
                        "paid_hours": 0.0,
                        "is_holiday": is_holiday,
                        "hour_rate": rate,
                        "multiplier": 0.0,
                        "payroll_additional": 0.0,
                    })
                    continue

                ordinary_part = min(hours, max(ordinary_remaining, 0.0))
                overtime_part = max(hours - ordinary_part, 0.0)
                if ordinary_part:
                    classification = "holiday_ordinary" if is_holiday else "ordinary"
                    if is_holiday:
                        multiplier = 1.0 if monthly else 2.0
                        amount = ordinary_part * rate * multiplier
                    else:
                        multiplier = 0.0 if monthly else 1.0
                        amount = ordinary_part * rate * multiplier
                    Line.create({
                        "analysis_id": rec.id,
                        "date_start": a.astimezone(pytz.UTC).replace(tzinfo=None),
                        "date_stop": (a + timedelta(hours=ordinary_part)).astimezone(pytz.UTC).replace(tzinfo=None),
                        "classification": classification,
                        "presence_hours": ordinary_part,
                        "paid_hours": ordinary_part,
                        "is_holiday": is_holiday,
                        "hour_rate": rate,
                        "multiplier": multiplier,
                        "payroll_additional": amount,
                    })
                    ordinary_remaining -= ordinary_part
                if overtime_part:
                    overtime_start = b - timedelta(hours=overtime_part)
                    classification = "holiday_overtime" if is_holiday else "overtime"
                    multiplier = 3.0 if is_holiday else 1.5
                    Line.create({
                        "analysis_id": rec.id,
                        "date_start": overtime_start.astimezone(pytz.UTC).replace(tzinfo=None),
                        "date_stop": b.astimezone(pytz.UTC).replace(tzinfo=None),
                        "classification": classification,
                        "presence_hours": overtime_part,
                        "paid_hours": overtime_part,
                        "is_holiday": is_holiday,
                        "hour_rate": rate,
                        "multiplier": multiplier,
                        "payroll_additional": overtime_part * rate * multiplier,
                    })
            rec.state = "calculated"
        return True

    def action_approve(self):
        for rec in self:
            if rec.state != "calculated":
                raise ValidationError(_("Primero debe calcular la segmentación."))
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
        return True

    def action_generate_incidents(self):
        Incident = self.env["cr.payroll.incident"].sudo()
        for rec in self:
            if rec.state != "approved":
                raise ValidationError(_("Debe aprobar el análisis antes de generar incidencias."))
            existing = Incident.search([
                ("cr_origin_model", "=", rec._name),
                ("cr_origin_id", "=", rec.id),
                ("state", "not in", ["cancel", "rejected"]),
            ])
            if existing:
                raise ValidationError(_("Este análisis ya generó incidencias."))
            for line in rec.line_ids:
                incident_type = {
                    "holiday_ordinary": "holiday_work",
                    "overtime": "overtime_15",
                    "holiday_overtime": "holiday_overtime",
                }.get(line.classification)
                if not incident_type:
                    continue
                # El motor base de Nómina CR espera horas en los inputs de horas.
                Incident.create({
                    "name": "%s - %s" % (rec.name, line.get_classification_label()),
                    "employee_id": rec.employee_id.id,
                    "contract_id": rec.contract_id.id,
                    "date": fields.Date.to_date(line.date_start),
                    "incident_type": incident_type,
                    "quantity": line.paid_hours,
                    "rate": 1.0,
                    "amount": line.paid_hours,
                    "description": "Segmento %s a %s. Tarifa informativa %.2f, multiplicador %.2f." % (line.date_start, line.date_stop, line.hour_rate, line.multiplier),
                    "state": "approved",
                    "cr_origin_model": rec._name,
                    "cr_origin_id": rec.id,
                    "cr_origin_period": "%s - %s" % (line.date_start, line.date_stop),
                    "cr_approved_by_id": rec.approved_by_id.id,
                    "cr_approved_at": rec.approved_at,
                })
            rec.state = "generated"
        return True


class CrPayrollShiftAnalysisLine(models.Model):
    _name = "cr.payroll.shift.analysis.line"
    _description = "Segmento de jornada avanzada CR"
    _order = "date_start,id"

    analysis_id = fields.Many2one("cr.payroll.shift.analysis", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="analysis_id.currency_id")
    date_start = fields.Datetime(required=True, readonly=True)
    date_stop = fields.Datetime(required=True, readonly=True)
    classification = fields.Selection([
        ("ordinary", "Ordinaria"),
        ("holiday_ordinary", "Ordinaria en feriado"),
        ("overtime", "Extra"),
        ("holiday_overtime", "Extra en feriado"),
        ("break", "Pausa no remunerada"),
    ], required=True, readonly=True)
    presence_hours = fields.Float(readonly=True)
    paid_hours = fields.Float(readonly=True)
    is_holiday = fields.Boolean(readonly=True)
    hour_rate = fields.Monetary(currency_field="currency_id", readonly=True)
    multiplier = fields.Float(readonly=True)
    payroll_additional = fields.Monetary(currency_field="currency_id", readonly=True)

    def get_classification_label(self):
        self.ensure_one()
        return dict(self._fields["classification"].selection).get(self.classification, self.classification)
