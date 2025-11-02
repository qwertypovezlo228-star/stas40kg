-- Get payment summary statistics
CREATE OR REPLACE FUNCTION public.get_payment_summary(
    start_date TIMESTAMPTZ DEFAULT (NOW() - INTERVAL '30 days'),
    end_date TIMESTAMPTZ DEFAULT NOW()
)
RETURNS JSONB
LANGUAGE SQL
AS $$
    SELECT jsonb_build_object(
        'total_revenue', COALESCE(SUM(amount), 0),
        'total_payments', COUNT(*),
        'avg_payment', COALESCE(AVG(amount), 0),
        'successful_payments', COUNT(*) FILTER (WHERE status = 'completed'),
        'failed_payments', COUNT(*) FILTER (WHERE status = 'failed'),
        'refunded_payments', COUNT(*) FILTER (WHERE status = 'refunded'),
        'revenue_by_plan', (
            SELECT jsonb_object_agg(
                COALESCE(plan_id::TEXT, 'unknown'), 
                jsonb_build_object(
                    'count', COUNT(*),
                    'revenue', SUM(amount),
                    'avg_amount', AVG(amount)
                )
            )
            FROM payments
            WHERE created_at BETWEEN start_date AND end_date
            GROUP BY plan_id
        ),
        'revenue_by_currency', (
            SELECT jsonb_object_agg(
                COALESCE(currency, 'USD'), 
                jsonb_build_object(
                    'count', COUNT(*),
                    'revenue', SUM(amount),
                    'avg_amount', AVG(amount)
                )
            )
            FROM payments
            WHERE created_at BETWEEN start_date AND end_date
            GROUP BY currency
        )
    )
    FROM payments
    WHERE created_at BETWEEN start_date AND end_date;
$$;

-- Get monthly revenue trend
CREATE OR REPLACE FUNCTION public.get_monthly_revenue()
RETURNS TABLE (
    month_date DATE,
    total_amount NUMERIC,
    payment_count BIGINT,
    avg_amount NUMERIC
)
LANGUAGE SQL
AS $$
    SELECT 
        DATE_TRUNC('month', created_at) AS month_date,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*) AS payment_count,
        COALESCE(AVG(amount), 0) AS avg_amount
    FROM payments
    WHERE status = 'completed'
    GROUP BY DATE_TRUNC('month', created_at)
    ORDER BY month_date DESC;
$$;

-- Get payment methods distribution
CREATE OR REPLACE FUNCTION public.get_payment_methods_distribution()
RETURNS JSONB
LANGUAGE SQL
AS $$
    SELECT 
        jsonb_build_object(
            'by_type', (
                SELECT jsonb_object_agg(
                    COALESCE(payment_type, 'unknown'),
                    jsonb_build_object(
                        'count', COUNT(*),
                        'revenue', COALESCE(SUM(amount), 0),
                        'avg_amount', COALESCE(AVG(amount), 0)
                    )
                )
                FROM payments
                GROUP BY payment_type
            ),
            'by_status', (
                SELECT jsonb_object_agg(
                    COALESCE(status, 'unknown'),
                    jsonb_build_object(
                        'count', COUNT(*),
                        'revenue', COALESCE(SUM(amount), 0)
                    )
                )
                FROM payments
                GROUP BY status
            )
        );
$$;

-- Get user statistics
CREATE OR REPLACE FUNCTION public.get_user_statistics(
    start_date TIMESTAMPTZ DEFAULT (NOW() - INTERVAL '30 days'),
    end_date TIMESTAMPTZ DEFAULT NOW()
)
RETURNS JSONB
LANGUAGE SQL
AS $$
    WITH user_stats AS (
        SELECT
            COUNT(*) AS total_users,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS new_users_7d,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS new_users_30d,
            COUNT(*) FILTER (WHERE last_activity >= NOW() - INTERVAL '1 day') AS active_users_1d,
            COUNT(*) FILTER (WHERE last_activity >= NOW() - INTERVAL '7 days') AS active_users_7d,
            COUNT(*) FILTER (WHERE last_activity >= NOW() - INTERVAL '30 days') AS active_users_30d
        FROM users
    ),
    user_growth AS (
        SELECT
            DATE_TRUNC('day', generate_series(
                start_date,
                end_date,
                INTERVAL '1 day'
            )) AS date,
            COUNT(*) AS new_users
        FROM users
        WHERE created_at BETWEEN start_date AND end_date
        GROUP BY DATE_TRUNC('day', created_at)
    )
    SELECT jsonb_build_object(
        'total_users', total_users,
        'new_users', jsonb_build_object(
            '7d', new_users_7d,
            '30d', new_users_30d
        ),
        'active_users', jsonb_build_object(
            '1d', active_users_1d,
            '7d', active_users_7d,
            '30d', active_users_30d
        ),
        'retention_rate', ROUND(
            (active_users_30d::FLOAT / NULLIF(COUNT(*) FILTER (WHERE created_at <= NOW() - INTERVAL '30 days'), 0) * 100)::NUMERIC,
            2
        ),
        'user_growth', (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'date', date,
                    'new_users', COALESCE(new_users, 0),
                    'cumulative_users', (
                        SELECT COUNT(*)
                        FROM users
                        WHERE created_at <= date
                    )
                )
                ORDER BY date
            )
            FROM user_growth
        )
    )
    FROM user_stats;
$$;

-- Get user engagement metrics
CREATE OR REPLACE FUNCTION public.get_user_engagement(days INTEGER DEFAULT 30)
RETURNS JSONB
LANGUAGE SQL
AS $$
    WITH user_actions AS (
        SELECT
            user_id,
            COUNT(*) AS action_count,
            COUNT(DISTINCT DATE(timestamp)) AS active_days,
            EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 3600 AS hours_between_first_last_action,
            COUNT(*) FILTER (WHERE action_type = 'payment') AS payment_actions,
            COUNT(*) FILTER (WHERE action_type = 'message') AS message_actions,
            COUNT(*) FILTER (WHERE action_type = 'button_click') AS button_actions
        FROM user_actions
        WHERE timestamp >= NOW() - (days || ' days')::INTERVAL
        GROUP BY user_id
    )
    SELECT jsonb_build_object(
        'total_actions', COALESCE(SUM(action_count), 0),
        'avg_actions_per_user', ROUND(COALESCE(AVG(action_count), 0)::NUMERIC, 2),
        'avg_active_days', ROUND(COALESCE(AVG(active_days), 0)::NUMERIC, 2),
        'avg_session_length_minutes', ROUND(COALESCE(AVG(
            CASE 
                WHEN hours_between_first_last_action > 0 
                THEN (hours_between_first_last_action * 60) / NULLIF(active_days, 0)
                ELSE 0 
            END
        ), 0)::NUMERIC, 2),
        'action_types', jsonb_build_object(
            'payments', COALESCE(SUM(payment_actions), 0),
            'messages', COALESCE(SUM(message_actions), 0),
            'button_clicks', COALESCE(SUM(button_actions), 0)
        ),
        'engagement_score', ROUND(COALESCE(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY 
                (active_days::FLOAT / days) * 
                (action_count::FLOAT / days) * 
                (1 + LEAST(hours_between_first_last_action / 24, 1))
            ), 0
        )::NUMERIC, 4) * 100
    )
    FROM user_actions;
$$;

-- Get conversion funnel
CREATE OR REPLACE FUNCTION public.get_conversion_funnel()
RETURNS JSONB
LANGUAGE SQL
AS $$
    WITH funnel AS (
        SELECT
            COUNT(DISTINCT user_id) FILTER (WHERE action = 'start_bot') AS started_bot,
            COUNT(DISTINCT user_id) FILTER (WHERE action = 'view_plans') AS viewed_plans,
            COUNT(DISTINCT user_id) FILTER (WHERE action = 'start_checkout') AS started_checkout,
            COUNT(DISTINCT user_id) FILTER (WHERE action = 'complete_payment') AS completed_payment,
            COUNT(DISTINCT user_id) FILTER (WHERE action = 'activate_plan') AS activated_plan
        FROM user_actions
        WHERE timestamp >= NOW() - INTERVAL '30 days'
    )
    SELECT jsonb_build_object(
        'steps', jsonb_build_array(
            jsonb_build_object('name', 'Started Bot', 'count', started_bot, 'conversion', 100.0),
            jsonb_build_object(
                'name', 'Viewed Plans', 
                'count', viewed_plans, 
                'conversion', ROUND((viewed_plans::FLOAT / NULLIF(started_bot, 0) * 100)::NUMERIC, 2)
            ),
            jsonb_build_object(
                'name', 'Started Checkout', 
                'count', started_checkout, 
                'conversion', ROUND((started_checkout::FLOAT / NULLIF(viewed_plans, 0) * 100)::NUMERIC, 2)
            ),
            jsonb_build_object(
                'name', 'Completed Payment', 
                'count', completed_payment, 
                'conversion', ROUND((completed_payment::FLOAT / NULLIF(started_checkout, 0) * 100)::NUMERIC, 2)
            ),
            jsonb_build_object(
                'name', 'Activated Plan', 
                'count', activated_plan, 
                'conversion', ROUND((activated_plan::FLOAT / NULLIF(completed_payment, 0) * 100)::NUMERIC, 2)
            )
        ),
        'overall_conversion', ROUND(
            (activated_plan::FLOAT / NULLIF(started_bot, 0) * 100)::NUMERIC,
            2
        )
    )
    FROM funnel;
$$;
