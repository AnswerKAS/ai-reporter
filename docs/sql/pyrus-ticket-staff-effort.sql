-- One row per ticket and actual worklog author; tickets without work are retained.
-- Aggregate before joining dimensions, so minutes and cost cannot multiply.
BEGIN;
CREATE VIEW pyrus_support_demo.ticket_staff_effort AS
WITH effort AS (
    SELECT ticket_id, agent_id,
           count(*)::integer AS worklog_count,
           sum(minutes)::bigint AS effort_minutes,
           sum(minutes)::numeric / 60 AS effort_hours,
           sum(cost_rub)::numeric(14,2) AS effort_cost_rub,
           min(worked_at) AS first_work_at,
           max(worked_at) AS last_work_at
    FROM pyrus_support_demo.worklogs
    GROUP BY ticket_id, agent_id
)
SELECT t.id AS ticket_id,
       t.pyrus_task_id,
       t.subject,
       t.status,
       t.priority,
       t.category,
       t.channel,
       t.created_at,
       t.first_response_at,
       t.resolved_at,
       t.closed_at,
       t.response_sla_breached,
       t.resolution_sla_breached,
       t.csat_score,
       t.reopen_count,
       t.escalated,
       t.snapshot_at,
       r.name AS requester_name,
       o.name AS organization_name,
       o.region,
       o.industry,
       o.support_tier,
       s.name AS service_name,
       assigned.name AS responsible_name,
       assigned_team.name AS responsible_team,
       e.agent_id AS employee_id,
       coalesce(a.name, 'Без трудозатрат') AS employee_name,
       team.name AS employee_team,
       a.hourly_cost_rub,
       coalesce(e.worklog_count, 0) AS worklog_count,
       coalesce(e.effort_minutes, 0) AS effort_minutes,
       coalesce(e.effort_hours, 0::numeric) AS effort_hours,
       coalesce(e.effort_cost_rub, 0::numeric) AS effort_cost_rub,
       e.first_work_at,
       e.last_work_at
FROM pyrus_support_demo.tickets t
LEFT JOIN effort e ON e.ticket_id = t.id
LEFT JOIN pyrus_support_demo.agents a ON a.id = e.agent_id
LEFT JOIN pyrus_support_demo.teams team ON team.id = a.team_id
LEFT JOIN pyrus_support_demo.agents assigned ON assigned.id = t.agent_id
LEFT JOIN pyrus_support_demo.teams assigned_team ON assigned_team.id = t.team_id
LEFT JOIN pyrus_support_demo.requesters r ON r.id = t.requester_id
LEFT JOIN pyrus_support_demo.organizations o ON o.id = r.organization_id
LEFT JOIN pyrus_support_demo.services s ON s.id = t.service_id;
COMMENT ON VIEW pyrus_support_demo.ticket_staff_effort IS
'Тестовая витрина Pyrus: одна строка на заявку и сотрудника, списавшего время. Заявки без списаний сохранены с нулевыми трудозатратами. Заявки считать COUNT(DISTINCT ticket_id), часы и стоимость суммировать. Ответственный и исполнитель трудозатрат могут различаться.';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.ticket_id IS 'Идентификатор заявки; может повторяться у разных сотрудников. Количество заявок = count(distinct ticket_id)';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.pyrus_task_id IS 'Синтетический идентификатор задачи Pyrus';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.subject IS 'Тема заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.status IS 'Статус заявки: new, in_progress, waiting_customer, resolved, closed';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.priority IS 'Приоритет заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.category IS 'Категория обращения';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.channel IS 'Канал обращения';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.created_at IS 'Дата создания заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.first_response_at IS 'Дата первого внешнего ответа сотрудника';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.resolved_at IS 'Дата окончательного решения заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.closed_at IS 'Дата закрытия заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.response_sla_breached IS 'Нарушен SLA первого ответа';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.resolution_sla_breached IS 'Нарушен SLA решения';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.csat_score IS 'Оценка клиента от 1 до 5; NULL, если оценки нет. При анализе по всем сотрудникам сначала оставить одну строку на ticket_id';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.reopen_count IS 'Повторные открытия заявки; при общем подсчёте сначала оставить одну строку на ticket_id';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.escalated IS 'Заявка эскалирована';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.snapshot_at IS 'Дата фиксированного снимка тестовых данных';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.requester_name IS 'Заявитель';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.organization_name IS 'Клиент';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.region IS 'Регион клиента';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.industry IS 'Отрасль клиента';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.support_tier IS 'Тариф поддержки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.service_name IS 'Сервис';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.responsible_name IS 'Ответственный за заявку';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.responsible_team IS 'Команда заявки';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.employee_id IS 'Идентификатор сотрудника, списавшего время; NULL у заявки без трудозатрат';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.employee_name IS 'Сотрудник, списавший время; «Без трудозатрат», если списаний нет';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.employee_team IS 'Команда сотрудника, списавшего время';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.hourly_cost_rub IS 'Стоимость часа сотрудника, рубли; не суммировать по строкам заявок';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.worklog_count IS 'Количество записей трудозатрат по заявке и сотруднику';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.effort_minutes IS 'Трудозатраты сотрудника по заявке, минуты; аддитивный показатель';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.effort_hours IS 'Трудозатраты сотрудника по заявке, часы; аддитивный показатель';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.effort_cost_rub IS 'Стоимость работы сотрудника по заявке, рубли; аддитивный показатель';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.first_work_at IS 'Первая запись трудозатрат сотрудника по заявке';
COMMENT ON COLUMN pyrus_support_demo.ticket_staff_effort.last_work_at IS 'Последняя запись трудозатрат сотрудника по заявке';
COMMIT;
