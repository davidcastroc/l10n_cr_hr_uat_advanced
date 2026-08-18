# RH Costa Rica - UAT Avanzado

Complemento para `l10n_cr_hr` enfocado en los escenarios excepcionales del UAT Nexus HRX.

## Cobertura

### UAT-01 Retroactivos
- Conserva los recibos cerrados originales.
- Calcula diferencias salariales sobre conceptos inequívocamente dependientes del salario.
- Permite ajustar manualmente cada diferencia antes de aprobar.
- Genera incidencias aprobadas en una fecha de nómina complementaria, con trazabilidad al recibo/período original.

### UAT-02 Eventos tardíos
- Registra documento único y evidencia obligatoria.
- Sustituye ausencias superpuestas por la incapacidad/licencia tardía.
- Si se superpone con `CR - Vacaciones`, rechaza la ausencia anterior para devolver el saldo a la asignación nativa.
- Identifica recibos cerrados afectados para que el ajuste sea procesado como complementaria sin reabrirlos.

### UAT-03 Liquidación avanzada
- Congela una referencia legal inalterable.
- Crea una capa de acuerdo negociado por extremo.
- Obliga motivo y evidencia para diferencias.
- Impide modificar/eliminar líneas una vez aprobado el acuerdo.
- Calcula saldo residual de préstamo como CxC pendiente.

### UAT-04 Jornada nocturna / feriado
- Divide automáticamente al cruzar medianoche.
- Excluye una pausa no remunerada.
- Consulta feriados públicos configurados en `resource.calendar.leaves`.
- Separa ordinarias, ordinarias en feriado, extras y extras en feriado.
- Distingue salario mensual vs. pago por hora.
- Genera incidencias de horas para el motor existente de Nómina CR.

## Nota funcional importante

Los escenarios UAT contienen decisiones empresariales y legales que no deben inferirse silenciosamente. Por eso los importes calculados por el complemento permanecen auditables y, donde corresponde, editables antes de aprobación.
