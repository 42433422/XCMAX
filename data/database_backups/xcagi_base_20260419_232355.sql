--
-- PostgreSQL database dump
--

\restrict gJZdtAT52GS4q5j5YhPNozqgJ2zb3BT0XJhf4ajfIntZKLjFWm9oQoPAndtCF0I

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_action_audit; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.ai_action_audit (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    actor text,
    action text NOT NULL,
    payload jsonb
);


ALTER TABLE public.ai_action_audit OWNER TO xcagi;

--
-- Name: ai_action_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.ai_action_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ai_action_audit_id_seq OWNER TO xcagi;

--
-- Name: ai_action_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.ai_action_audit_id_seq OWNED BY public.ai_action_audit.id;


--
-- Name: ai_conversation_sessions; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.ai_conversation_sessions (
    id bigint NOT NULL,
    session_id character varying NOT NULL,
    user_id integer,
    title character varying,
    summary character varying,
    message_count integer DEFAULT 0,
    last_message_at timestamp without time zone,
    created_at timestamp without time zone
);


ALTER TABLE public.ai_conversation_sessions OWNER TO xcagi;

--
-- Name: ai_conversation_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.ai_conversation_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ai_conversation_sessions_id_seq OWNER TO xcagi;

--
-- Name: ai_conversation_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.ai_conversation_sessions_id_seq OWNED BY public.ai_conversation_sessions.id;


--
-- Name: ai_conversations; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.ai_conversations (
    id bigint NOT NULL,
    session_id character varying NOT NULL,
    user_id character varying,
    role character varying NOT NULL,
    content text NOT NULL,
    intent character varying,
    conversation_metadata text,
    created_at timestamp without time zone
);


ALTER TABLE public.ai_conversations OWNER TO xcagi;

--
-- Name: ai_conversations_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.ai_conversations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ai_conversations_id_seq OWNER TO xcagi;

--
-- Name: ai_conversations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.ai_conversations_id_seq OWNED BY public.ai_conversations.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO xcagi;

--
-- Name: approval_delegations; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.approval_delegations (
    id integer NOT NULL,
    delegator_id integer NOT NULL,
    delegate_id integer NOT NULL,
    flow_ids text,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    reason character varying(512),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    created_by integer
);


ALTER TABLE public.approval_delegations OWNER TO xcagi;

--
-- Name: approval_delegations_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.approval_delegations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_delegations_id_seq OWNER TO xcagi;

--
-- Name: approval_delegations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.approval_delegations_id_seq OWNED BY public.approval_delegations.id;


--
-- Name: approval_flow_nodes; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.approval_flow_nodes (
    id integer NOT NULL,
    flow_id integer NOT NULL,
    node_name character varying(128) NOT NULL,
    node_order integer NOT NULL,
    node_type character varying(32) DEFAULT 'serial'::character varying,
    approver_type character varying(32) NOT NULL,
    approver_ids text,
    min_approvals integer DEFAULT 1,
    condition_expression text,
    condition_description character varying(256),
    timeout_hours integer,
    timeout_action character varying(32) DEFAULT 'notify'::character varying,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.approval_flow_nodes OWNER TO xcagi;

--
-- Name: approval_flow_nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.approval_flow_nodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_flow_nodes_id_seq OWNER TO xcagi;

--
-- Name: approval_flow_nodes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.approval_flow_nodes_id_seq OWNED BY public.approval_flow_nodes.id;


--
-- Name: approval_flows; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.approval_flows (
    id integer NOT NULL,
    flow_key character varying(64) NOT NULL,
    flow_name character varying(128) NOT NULL,
    description text,
    industry character varying(64) DEFAULT '閫氱敤'::character varying,
    node_type character varying(32) DEFAULT 'serial'::character varying,
    allow_transfer boolean DEFAULT true,
    allow_delegate boolean DEFAULT false,
    allow_withdraw boolean DEFAULT true,
    timeout_hours integer DEFAULT 48,
    is_active boolean DEFAULT true,
    is_deleted boolean DEFAULT false,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    business_type character varying(64) DEFAULT 'general'::character varying
);


ALTER TABLE public.approval_flows OWNER TO xcagi;

--
-- Name: approval_flows_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.approval_flows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_flows_id_seq OWNER TO xcagi;

--
-- Name: approval_flows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.approval_flows_id_seq OWNED BY public.approval_flows.id;


--
-- Name: approval_records; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.approval_records (
    id integer NOT NULL,
    request_id integer NOT NULL,
    node_id integer NOT NULL,
    node_name character varying(128),
    node_order integer,
    approver_id integer NOT NULL,
    approver_name character varying(64),
    action character varying(32) NOT NULL,
    opinion text,
    reject_reason character varying(512),
    is_passed boolean DEFAULT false,
    transferred_from integer,
    transferred_to integer,
    delegate_user integer,
    action_time timestamp with time zone DEFAULT now(),
    deadline timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.approval_records OWNER TO xcagi;

--
-- Name: approval_records_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.approval_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_records_id_seq OWNER TO xcagi;

--
-- Name: approval_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.approval_records_id_seq OWNED BY public.approval_records.id;


--
-- Name: approval_requests; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.approval_requests (
    id integer NOT NULL,
    request_no character varying(64) NOT NULL,
    flow_id integer NOT NULL,
    business_type character varying(64) NOT NULL,
    business_id integer,
    business_data text,
    applicant_id integer NOT NULL,
    applicant_name character varying(64),
    applicant_department character varying(64),
    title character varying(256) NOT NULL,
    description text,
    current_node_id integer,
    current_node_order integer DEFAULT 1,
    status character varying(32) DEFAULT 'pending'::character varying,
    priority character varying(16) DEFAULT 'normal'::character varying,
    submitted_at timestamp with time zone DEFAULT now(),
    approved_at timestamp with time zone,
    rejected_at timestamp with time zone,
    expired_at timestamp with time zone,
    approved_by integer,
    approved_by_name character varying(64),
    rejection_reason character varying(512),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.approval_requests OWNER TO xcagi;

--
-- Name: approval_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.approval_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_requests_id_seq OWNER TO xcagi;

--
-- Name: approval_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.approval_requests_id_seq OWNED BY public.approval_requests.id;


--
-- Name: distillation_log; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.distillation_log (
    id bigint NOT NULL,
    query text NOT NULL,
    intent text NOT NULL,
    slots text,
    confidence double precision DEFAULT 1.0,
    source text DEFAULT 'manual'::text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    used_for_training integer DEFAULT 0
);


ALTER TABLE public.distillation_log OWNER TO xcagi;

--
-- Name: distillation_log_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.distillation_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.distillation_log_id_seq OWNER TO xcagi;

--
-- Name: distillation_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.distillation_log_id_seq OWNED BY public.distillation_log.id;


--
-- Name: document_templates; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.document_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug character varying(64) NOT NULL,
    display_name character varying(255) NOT NULL,
    role character varying(32) NOT NULL,
    storage_relpath text NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    file_format character varying(16) DEFAULT 'docx'::character varying NOT NULL,
    business_scope character varying(64),
    editor_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    legacy_sqlite_id character varying(36)
);


ALTER TABLE public.document_templates OWNER TO xcagi;

--
-- Name: excel_vector_chunks; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.excel_vector_chunks (
    chunk_id text NOT NULL,
    index_id text NOT NULL,
    content text NOT NULL,
    embedding public.vector(256) NOT NULL,
    metadata jsonb NOT NULL,
    created_at double precision NOT NULL
);


ALTER TABLE public.excel_vector_chunks OWNER TO xcagi;

--
-- Name: excel_vector_indexes; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.excel_vector_indexes (
    index_id text NOT NULL,
    name text NOT NULL,
    source_file text NOT NULL,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.excel_vector_indexes OWNER TO xcagi;

--
-- Name: extract_logs; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.extract_logs (
    id bigint NOT NULL,
    file_name text,
    file_path text,
    data_type text,
    total_rows integer DEFAULT 0,
    valid_rows integer,
    imported_rows integer,
    skipped_rows integer,
    failed_rows integer,
    status text DEFAULT 'pending'::text,
    error_message text,
    field_mapping text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.extract_logs OWNER TO xcagi;

--
-- Name: extract_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.extract_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.extract_logs_id_seq OWNER TO xcagi;

--
-- Name: extract_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.extract_logs_id_seq OWNED BY public.extract_logs.id;


--
-- Name: inventory_ledger; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.inventory_ledger (
    id integer NOT NULL,
    product_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    location_id integer,
    batch_no character varying(50),
    quantity numeric(18,4),
    available_quantity numeric(18,4),
    reserved_quantity numeric(18,4),
    unit character varying(20),
    in_date date,
    expire_date date,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.inventory_ledger OWNER TO xcagi;

--
-- Name: inventory_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.inventory_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.inventory_ledger_id_seq OWNER TO xcagi;

--
-- Name: inventory_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.inventory_ledger_id_seq OWNED BY public.inventory_ledger.id;


--
-- Name: inventory_transactions; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.inventory_transactions (
    id integer NOT NULL,
    ledger_id integer,
    transaction_type character varying(20) NOT NULL,
    product_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    location_id integer,
    batch_no character varying(50),
    quantity numeric(18,4) NOT NULL,
    before_quantity numeric(18,4),
    after_quantity numeric(18,4),
    unit_price numeric(18,4),
    total_amount numeric(18,2),
    reference_type character varying(50),
    reference_id integer,
    transaction_date timestamp without time zone NOT NULL,
    operator character varying(50),
    remark text,
    created_at timestamp without time zone
);


ALTER TABLE public.inventory_transactions OWNER TO xcagi;

--
-- Name: inventory_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.inventory_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.inventory_transactions_id_seq OWNER TO xcagi;

--
-- Name: inventory_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.inventory_transactions_id_seq OWNED BY public.inventory_transactions.id;


--
-- Name: mp_addresses; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_addresses (
    id integer NOT NULL,
    user_id integer NOT NULL,
    contact_name character varying(32) NOT NULL,
    contact_phone character varying(20) NOT NULL,
    province character varying(32) NOT NULL,
    city character varying(32) NOT NULL,
    district character varying(32) NOT NULL,
    detail_address text NOT NULL,
    is_default boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_addresses OWNER TO xcagi;

--
-- Name: mp_addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_addresses_id_seq OWNER TO xcagi;

--
-- Name: mp_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_addresses_id_seq OWNED BY public.mp_addresses.id;


--
-- Name: mp_browse_history; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_browse_history (
    id integer NOT NULL,
    user_id integer NOT NULL,
    product_id integer NOT NULL,
    viewed_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_browse_history OWNER TO xcagi;

--
-- Name: mp_browse_history_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_browse_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_browse_history_id_seq OWNER TO xcagi;

--
-- Name: mp_browse_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_browse_history_id_seq OWNED BY public.mp_browse_history.id;


--
-- Name: mp_carts; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_carts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    product_id integer NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    selected boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_carts OWNER TO xcagi;

--
-- Name: mp_carts_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_carts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_carts_id_seq OWNER TO xcagi;

--
-- Name: mp_carts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_carts_id_seq OWNED BY public.mp_carts.id;


--
-- Name: mp_favorites; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_favorites (
    id integer NOT NULL,
    user_id integer NOT NULL,
    product_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_favorites OWNER TO xcagi;

--
-- Name: mp_favorites_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_favorites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_favorites_id_seq OWNER TO xcagi;

--
-- Name: mp_favorites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_favorites_id_seq OWNED BY public.mp_favorites.id;


--
-- Name: mp_feedbacks; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_feedbacks (
    id integer NOT NULL,
    user_id integer NOT NULL,
    type character varying(32) NOT NULL,
    content text NOT NULL,
    images text,
    status character varying(20) DEFAULT 'pending'::character varying,
    reply text,
    replied_by integer,
    replied_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_feedbacks OWNER TO xcagi;

--
-- Name: mp_feedbacks_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_feedbacks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_feedbacks_id_seq OWNER TO xcagi;

--
-- Name: mp_feedbacks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_feedbacks_id_seq OWNED BY public.mp_feedbacks.id;


--
-- Name: mp_notifications; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_notifications (
    id integer NOT NULL,
    user_id integer NOT NULL,
    title character varying(128) NOT NULL,
    content text,
    type character varying(32) DEFAULT 'system'::character varying,
    is_read boolean DEFAULT false,
    related_type character varying(32),
    related_id integer,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_notifications OWNER TO xcagi;

--
-- Name: mp_notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_notifications_id_seq OWNER TO xcagi;

--
-- Name: mp_notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_notifications_id_seq OWNED BY public.mp_notifications.id;


--
-- Name: mp_order_items; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_order_items (
    id integer NOT NULL,
    order_id integer NOT NULL,
    product_id integer NOT NULL,
    product_name character varying(128) NOT NULL,
    product_sku character varying(64),
    quantity integer NOT NULL,
    unit_price numeric(10,2) NOT NULL,
    subtotal numeric(12,2) NOT NULL,
    remark text
);


ALTER TABLE public.mp_order_items OWNER TO xcagi;

--
-- Name: mp_order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_order_items_id_seq OWNER TO xcagi;

--
-- Name: mp_order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_order_items_id_seq OWNED BY public.mp_order_items.id;


--
-- Name: mp_orders; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.mp_orders (
    id integer NOT NULL,
    order_no character varying(32) NOT NULL,
    user_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    total_amount numeric(12,2) NOT NULL,
    pay_amount numeric(12,2),
    pay_status character varying(20) DEFAULT 'unpaid'::character varying,
    pay_time timestamp with time zone,
    delivery_name character varying(64),
    delivery_phone character varying(20),
    delivery_address text,
    delivery_province character varying(32),
    delivery_city character varying(32),
    delivery_district character varying(32),
    remark text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.mp_orders OWNER TO xcagi;

--
-- Name: mp_orders_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.mp_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mp_orders_id_seq OWNER TO xcagi;

--
-- Name: mp_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.mp_orders_id_seq OWNED BY public.mp_orders.id;


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.permissions (
    id bigint NOT NULL,
    name character varying NOT NULL,
    code character varying NOT NULL,
    description character varying DEFAULT ''::character varying,
    module character varying DEFAULT ''::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.permissions OWNER TO xcagi;

--
-- Name: permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.permissions_id_seq OWNER TO xcagi;

--
-- Name: permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.products (
    id bigint NOT NULL,
    model_number character varying,
    name character varying NOT NULL,
    specification character varying,
    price double precision DEFAULT 0,
    quantity integer,
    description character varying,
    category character varying,
    brand character varying,
    unit character varying DEFAULT '涓?::character varying,
    is_active integer DEFAULT 1,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.products OWNER TO xcagi;

--
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.products_id_seq OWNER TO xcagi;

--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- Name: purchase_inbound_items; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.purchase_inbound_items (
    id integer NOT NULL,
    inbound_id integer NOT NULL,
    product_id integer NOT NULL,
    order_item_id integer,
    product_name character varying(200),
    batch_no character varying(50),
    quantity numeric(18,4) NOT NULL,
    unit character varying(20),
    unit_price numeric(18,4),
    amount numeric(18,2),
    location_id integer,
    remark text,
    created_at timestamp without time zone
);


ALTER TABLE public.purchase_inbound_items OWNER TO xcagi;

--
-- Name: purchase_inbound_items_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.purchase_inbound_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.purchase_inbound_items_id_seq OWNER TO xcagi;

--
-- Name: purchase_inbound_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.purchase_inbound_items_id_seq OWNED BY public.purchase_inbound_items.id;


--
-- Name: purchase_inbounds; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.purchase_inbounds (
    id integer NOT NULL,
    inbound_no character varying(50) NOT NULL,
    order_id integer,
    supplier_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    inbound_date date NOT NULL,
    total_amount numeric(18,2),
    status character varying(20),
    handler character varying(50),
    remark text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.purchase_inbounds OWNER TO xcagi;

--
-- Name: purchase_inbounds_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.purchase_inbounds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.purchase_inbounds_id_seq OWNER TO xcagi;

--
-- Name: purchase_inbounds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.purchase_inbounds_id_seq OWNED BY public.purchase_inbounds.id;


--
-- Name: purchase_order_items; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.purchase_order_items (
    id integer NOT NULL,
    order_id integer NOT NULL,
    product_id integer NOT NULL,
    product_name character varying(200),
    specification character varying(200),
    quantity numeric(18,4) NOT NULL,
    unit character varying(20),
    unit_price numeric(18,4),
    amount numeric(18,2),
    received_quantity numeric(18,4),
    invoiced_quantity numeric(18,4),
    status character varying(20),
    remark text,
    created_at timestamp without time zone
);


ALTER TABLE public.purchase_order_items OWNER TO xcagi;

--
-- Name: purchase_order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.purchase_order_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.purchase_order_items_id_seq OWNER TO xcagi;

--
-- Name: purchase_order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.purchase_order_items_id_seq OWNED BY public.purchase_order_items.id;


--
-- Name: purchase_orders; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.purchase_orders (
    id integer NOT NULL,
    order_no character varying(50) NOT NULL,
    supplier_id integer NOT NULL,
    warehouse_id integer,
    order_date date NOT NULL,
    delivery_date date,
    total_amount numeric(18,2),
    paid_amount numeric(18,2),
    status character varying(20),
    approver character varying(50),
    approve_date timestamp without time zone,
    remark text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.purchase_orders OWNER TO xcagi;

--
-- Name: purchase_orders_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.purchase_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.purchase_orders_id_seq OWNER TO xcagi;

--
-- Name: purchase_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.purchase_orders_id_seq OWNED BY public.purchase_orders.id;


--
-- Name: purchase_units; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.purchase_units (
    id bigint NOT NULL,
    unit_name character varying(255) NOT NULL,
    contact_person character varying(100),
    contact_phone character varying(50),
    address character varying(500),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.purchase_units OWNER TO xcagi;

--
-- Name: purchase_units_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.purchase_units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.purchase_units_id_seq OWNER TO xcagi;

--
-- Name: purchase_units_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.purchase_units_id_seq OWNED BY public.purchase_units.id;


--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.role_permissions (
    role_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.role_permissions OWNER TO xcagi;

--
-- Name: roles; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.roles (
    id bigint NOT NULL,
    name character varying NOT NULL,
    description character varying DEFAULT ''::character varying,
    is_system boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.roles OWNER TO xcagi;

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.roles_id_seq OWNER TO xcagi;

--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: shipment_records; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.shipment_records (
    id bigint NOT NULL,
    purchase_unit character varying NOT NULL,
    unit_id integer,
    product_name character varying NOT NULL,
    model_number character varying,
    quantity_kg double precision NOT NULL,
    quantity_tins integer NOT NULL,
    tin_spec double precision,
    unit_price double precision DEFAULT 0,
    amount double precision DEFAULT 0,
    status character varying DEFAULT 'pending'::character varying,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    printed_at timestamp without time zone,
    printer_name character varying,
    raw_text text,
    parsed_data text
);


ALTER TABLE public.shipment_records OWNER TO xcagi;

--
-- Name: shipment_records_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.shipment_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.shipment_records_id_seq OWNER TO xcagi;

--
-- Name: shipment_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.shipment_records_id_seq OWNED BY public.shipment_records.id;


--
-- Name: storage_locations; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.storage_locations (
    id integer NOT NULL,
    warehouse_id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100),
    max_capacity numeric(18,4),
    current_capacity numeric(18,4),
    status character varying(20),
    created_at timestamp without time zone
);


ALTER TABLE public.storage_locations OWNER TO xcagi;

--
-- Name: storage_locations_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.storage_locations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.storage_locations_id_seq OWNER TO xcagi;

--
-- Name: storage_locations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.storage_locations_id_seq OWNED BY public.storage_locations.id;


--
-- Name: suppliers; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.suppliers (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    contact_person character varying(50),
    contact_phone character varying(50),
    contact_email character varying(100),
    address text,
    payment_terms character varying(50),
    credit_limit numeric(18,2),
    status character varying(20),
    rating integer,
    remark text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.suppliers OWNER TO xcagi;

--
-- Name: suppliers_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.suppliers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.suppliers_id_seq OWNER TO xcagi;

--
-- Name: suppliers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.suppliers_id_seq OWNED BY public.suppliers.id;


--
-- Name: template_usage_log; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.template_usage_log (
    id bigint NOT NULL,
    template_id bigint NOT NULL,
    action text NOT NULL,
    result text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.template_usage_log OWNER TO xcagi;

--
-- Name: template_usage_log_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.template_usage_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_usage_log_id_seq OWNER TO xcagi;

--
-- Name: template_usage_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.template_usage_log_id_seq OWNED BY public.template_usage_log.id;


--
-- Name: templates; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.templates (
    id bigint NOT NULL,
    template_key text,
    template_name text NOT NULL,
    template_type text,
    original_file_path text,
    analyzed_data text,
    editable_config text,
    zone_config text,
    merged_cells_config text,
    style_config text,
    business_rules text,
    is_active integer DEFAULT 1,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.templates OWNER TO xcagi;

--
-- Name: templates_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.templates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.templates_id_seq OWNER TO xcagi;

--
-- Name: templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.templates_id_seq OWNED BY public.templates.id;


--
-- Name: training_stats; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.training_stats (
    id bigint NOT NULL,
    intent text NOT NULL,
    count integer DEFAULT 0,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.training_stats OWNER TO xcagi;

--
-- Name: training_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.training_stats_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.training_stats_id_seq OWNER TO xcagi;

--
-- Name: training_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.training_stats_id_seq OWNED BY public.training_stats.id;


--
-- Name: user_memories; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.user_memories (
    id bigint NOT NULL,
    user_id character varying NOT NULL,
    preferences text,
    frequent_actions text,
    historical_contexts text,
    feedback_history text,
    updated_at timestamp without time zone
);


ALTER TABLE public.user_memories OWNER TO xcagi;

--
-- Name: user_memories_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.user_memories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_memories_id_seq OWNER TO xcagi;

--
-- Name: user_memories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.user_memories_id_seq OWNED BY public.user_memories.id;


--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.user_preferences (
    id bigint NOT NULL,
    user_id character varying NOT NULL,
    preference_key character varying NOT NULL,
    preference_value text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.user_preferences OWNER TO xcagi;

--
-- Name: user_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.user_preferences_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_preferences_id_seq OWNER TO xcagi;

--
-- Name: user_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.user_preferences_id_seq OWNED BY public.user_preferences.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    username character varying NOT NULL,
    password character varying NOT NULL,
    display_name character varying DEFAULT ''::character varying,
    email character varying DEFAULT ''::character varying,
    role character varying DEFAULT 'user'::character varying,
    is_active boolean DEFAULT true,
    created_by integer,
    created_at timestamp without time zone,
    last_login timestamp without time zone,
    wx_openid character varying(64),
    wx_unionid character varying(64),
    wx_avatar_url text,
    mp_phone character varying(20),
    mp_nickname character varying(64)
);


ALTER TABLE public.users OWNER TO xcagi;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO xcagi;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: warehouses; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.warehouses (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    type character varying(20),
    address text,
    manager character varying(50),
    status character varying(20),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.warehouses OWNER TO xcagi;

--
-- Name: warehouses_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.warehouses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.warehouses_id_seq OWNER TO xcagi;

--
-- Name: warehouses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.warehouses_id_seq OWNED BY public.warehouses.id;


--
-- Name: wechat_contact_context; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.wechat_contact_context (
    id bigint NOT NULL,
    contact_id integer NOT NULL,
    wechat_id character varying,
    context_json text,
    message_count integer DEFAULT 0,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.wechat_contact_context OWNER TO xcagi;

--
-- Name: wechat_contact_context_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.wechat_contact_context_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.wechat_contact_context_id_seq OWNER TO xcagi;

--
-- Name: wechat_contact_context_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.wechat_contact_context_id_seq OWNED BY public.wechat_contact_context.id;


--
-- Name: wechat_contacts; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.wechat_contacts (
    id bigint NOT NULL,
    contact_name character varying NOT NULL,
    remark character varying,
    wechat_id character varying,
    contact_type character varying DEFAULT 'contact'::character varying,
    is_active integer DEFAULT 1,
    is_starred integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.wechat_contacts OWNER TO xcagi;

--
-- Name: wechat_contacts_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.wechat_contacts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.wechat_contacts_id_seq OWNER TO xcagi;

--
-- Name: wechat_contacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.wechat_contacts_id_seq OWNED BY public.wechat_contacts.id;


--
-- Name: wechat_tasks; Type: TABLE; Schema: public; Owner: xcagi
--

CREATE TABLE public.wechat_tasks (
    id bigint NOT NULL,
    contact_id integer,
    username character varying,
    display_name character varying,
    message_id character varying,
    msg_timestamp integer,
    raw_text text NOT NULL,
    task_type character varying DEFAULT 'unknown'::character varying,
    status character varying DEFAULT 'pending'::character varying,
    last_status_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.wechat_tasks OWNER TO xcagi;

--
-- Name: wechat_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: xcagi
--

CREATE SEQUENCE public.wechat_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.wechat_tasks_id_seq OWNER TO xcagi;

--
-- Name: wechat_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xcagi
--

ALTER SEQUENCE public.wechat_tasks_id_seq OWNED BY public.wechat_tasks.id;


--
-- Name: ai_action_audit id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_action_audit ALTER COLUMN id SET DEFAULT nextval('public.ai_action_audit_id_seq'::regclass);


--
-- Name: ai_conversation_sessions id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversation_sessions ALTER COLUMN id SET DEFAULT nextval('public.ai_conversation_sessions_id_seq'::regclass);


--
-- Name: ai_conversations id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversations ALTER COLUMN id SET DEFAULT nextval('public.ai_conversations_id_seq'::regclass);


--
-- Name: approval_delegations id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_delegations ALTER COLUMN id SET DEFAULT nextval('public.approval_delegations_id_seq'::regclass);


--
-- Name: approval_flow_nodes id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flow_nodes ALTER COLUMN id SET DEFAULT nextval('public.approval_flow_nodes_id_seq'::regclass);


--
-- Name: approval_flows id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flows ALTER COLUMN id SET DEFAULT nextval('public.approval_flows_id_seq'::regclass);


--
-- Name: approval_records id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records ALTER COLUMN id SET DEFAULT nextval('public.approval_records_id_seq'::regclass);


--
-- Name: approval_requests id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests ALTER COLUMN id SET DEFAULT nextval('public.approval_requests_id_seq'::regclass);


--
-- Name: distillation_log id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.distillation_log ALTER COLUMN id SET DEFAULT nextval('public.distillation_log_id_seq'::regclass);


--
-- Name: extract_logs id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.extract_logs ALTER COLUMN id SET DEFAULT nextval('public.extract_logs_id_seq'::regclass);


--
-- Name: inventory_ledger id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_ledger ALTER COLUMN id SET DEFAULT nextval('public.inventory_ledger_id_seq'::regclass);


--
-- Name: inventory_transactions id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions ALTER COLUMN id SET DEFAULT nextval('public.inventory_transactions_id_seq'::regclass);


--
-- Name: mp_addresses id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_addresses ALTER COLUMN id SET DEFAULT nextval('public.mp_addresses_id_seq'::regclass);


--
-- Name: mp_browse_history id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_browse_history ALTER COLUMN id SET DEFAULT nextval('public.mp_browse_history_id_seq'::regclass);


--
-- Name: mp_carts id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_carts ALTER COLUMN id SET DEFAULT nextval('public.mp_carts_id_seq'::regclass);


--
-- Name: mp_favorites id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_favorites ALTER COLUMN id SET DEFAULT nextval('public.mp_favorites_id_seq'::regclass);


--
-- Name: mp_feedbacks id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_feedbacks ALTER COLUMN id SET DEFAULT nextval('public.mp_feedbacks_id_seq'::regclass);


--
-- Name: mp_notifications id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_notifications ALTER COLUMN id SET DEFAULT nextval('public.mp_notifications_id_seq'::regclass);


--
-- Name: mp_order_items id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_order_items ALTER COLUMN id SET DEFAULT nextval('public.mp_order_items_id_seq'::regclass);


--
-- Name: mp_orders id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_orders ALTER COLUMN id SET DEFAULT nextval('public.mp_orders_id_seq'::regclass);


--
-- Name: permissions id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- Name: purchase_inbound_items id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items ALTER COLUMN id SET DEFAULT nextval('public.purchase_inbound_items_id_seq'::regclass);


--
-- Name: purchase_inbounds id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds ALTER COLUMN id SET DEFAULT nextval('public.purchase_inbounds_id_seq'::regclass);


--
-- Name: purchase_order_items id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_order_items ALTER COLUMN id SET DEFAULT nextval('public.purchase_order_items_id_seq'::regclass);


--
-- Name: purchase_orders id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_orders ALTER COLUMN id SET DEFAULT nextval('public.purchase_orders_id_seq'::regclass);


--
-- Name: purchase_units id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_units ALTER COLUMN id SET DEFAULT nextval('public.purchase_units_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: shipment_records id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.shipment_records ALTER COLUMN id SET DEFAULT nextval('public.shipment_records_id_seq'::regclass);


--
-- Name: storage_locations id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.storage_locations ALTER COLUMN id SET DEFAULT nextval('public.storage_locations_id_seq'::regclass);


--
-- Name: suppliers id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.suppliers ALTER COLUMN id SET DEFAULT nextval('public.suppliers_id_seq'::regclass);


--
-- Name: template_usage_log id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.template_usage_log ALTER COLUMN id SET DEFAULT nextval('public.template_usage_log_id_seq'::regclass);


--
-- Name: templates id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.templates ALTER COLUMN id SET DEFAULT nextval('public.templates_id_seq'::regclass);


--
-- Name: training_stats id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.training_stats ALTER COLUMN id SET DEFAULT nextval('public.training_stats_id_seq'::regclass);


--
-- Name: user_memories id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.user_memories ALTER COLUMN id SET DEFAULT nextval('public.user_memories_id_seq'::regclass);


--
-- Name: user_preferences id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.user_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_preferences_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: warehouses id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.warehouses ALTER COLUMN id SET DEFAULT nextval('public.warehouses_id_seq'::regclass);


--
-- Name: wechat_contact_context id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_contact_context ALTER COLUMN id SET DEFAULT nextval('public.wechat_contact_context_id_seq'::regclass);


--
-- Name: wechat_contacts id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_contacts ALTER COLUMN id SET DEFAULT nextval('public.wechat_contacts_id_seq'::regclass);


--
-- Name: wechat_tasks id; Type: DEFAULT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_tasks ALTER COLUMN id SET DEFAULT nextval('public.wechat_tasks_id_seq'::regclass);


--
-- Data for Name: ai_action_audit; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.ai_action_audit (id, created_at, actor, action, payload) FROM stdin;
1	2026-04-19 11:38:34.545316+00	4	approval.submit	{"flow_id": 12, "flow_key": "shipment_approval_v2", "request_id": 9, "request_no": "APR20260419-D04BE1", "business_id": null, "business_type": "shipment", "first_node_id": 23}
2	2026-04-19 11:47:06.264084+00	4	approval.approve	{"flow_id": 10, "node_id": 20, "opinion": "鍚屾剰", "request_id": 7, "request_no": "ARSHI202604171208471C1335", "next_node_id": null, "status_after": "approved", "status_before": "in_progress"}
3	2026-04-19 11:59:39.021938+00	4	approval.reject	{"reason": "2", "flow_id": 8, "node_id": 16, "request_id": 6, "request_no": "ARSHI20260417120648904384", "status_after": "rejected", "status_before": "in_progress"}
4	2026-04-19 11:59:42.140108+00	4	approval.reject	{"reason": "2", "flow_id": 7, "node_id": 14, "request_id": 5, "request_no": "ARSHI20260417120435B32E18", "status_after": "rejected", "status_before": "in_progress"}
5	2026-04-19 14:16:37.158165+00	4	approval.cleanup	{"count": 3, "statuses": ["approved", "rejected", "withdrawn", "cancelled"], "before_days": null, "request_ids": [7, 6, 5], "request_nos": ["ARSHI202604171208471C1335", "ARSHI20260417120648904384", "ARSHI20260417120435B32E18"]}
\.


--
-- Data for Name: ai_conversation_sessions; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.ai_conversation_sessions (id, session_id, user_id, title, summary, message_count, last_message_at, created_at) FROM stdin;
1	reg-71ffedbde023	\N	\N	\N	1	2026-03-27 03:08:22.844613	2026-03-27 03:08:22.844613
2	mn-fc4aac3f7ce8	\N	\N	\N	1	2026-03-27 03:11:16.447602	2026-03-27 03:11:16.447602
3	mn7uww7jdgcckw8ktbs	\N	\N	\N	4	2026-03-27 03:21:23.375774	2026-03-27 03:21:15.355222
4	mn7uzh8exghhvtexth	\N	\N	\N	4	2026-03-27 03:22:13.578801	2026-03-27 03:22:05.699318
\.


--
-- Data for Name: ai_conversations; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.ai_conversations (id, session_id, user_id, role, content, intent, conversation_metadata, created_at) FROM stdin;
1	reg-71ffedbde023	default	user	娴嬭瘯娑堟伅	greet	{}	2026-03-27 03:08:22.864003
2	mn-fc4aac3f7ce8	\N	user	hello			2026-03-27 03:11:16.451349
3	mn7uww7jdgcckw8ktbs	\N	user	寮€濮嬪垎鏋?Excel锛氭潨鍏嬫棗.xlsx			2026-03-27 03:21:15.359951
4	mn7uww7jdgcckw8ktbs	\N	assistant	Excel 鍒嗘瀽瀹屾垚\n宸ヤ綔琛細鍑鸿揣\n璇嶆潯鏁伴噺锛?2\n璇嶆潯锛氬巶鍚嶃€佹棩鏈熴€佸崟鍙枫€佷骇鍝佸瀷鍙枫€佷骇鍝佸悕绉般€佹暟閲?浠躲€佽鏍?KG銆佹暟閲?KG銆佸崟浠?鍏冦€侀噾棰?鍏冦€佸娉ㄣ€侀噾棰濆悎璁n缃戞牸琛屾暟锛?0\n鏍蜂緥鏁版嵁锛歕n1. 浜у搧鍚嶇О:PU鐧藉簳婕嗭紱浜у搧鍨嬪彿:D904锛涘崟浠?鍏?7锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:9804\n2. 浜у搧鍚嶇О:PU鍝戝厜鐧介潰婕嗭紙涓夊垎鍏夛級锛涗骇鍝佸瀷鍙?D850锛涘崟浠?鍏?12锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:婢滃畤鍝戠櫧\n3. 浜у搧鍚嶇О:PU鍝戝厜鍥哄寲鍓傦紱浜у搧鍨嬪彿:D303锛涘崟浠?鍏?12锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:303			2026-03-27 03:21:17.35659
5	mn7uww7jdgcckw8ktbs	\N	user	鍔犲叆鏁版嵁搴?		2026-03-27 03:21:23.243561
6	mn7uww7jdgcckw8ktbs	\N	assistant	宸叉寜鑱婂ぉ璇锋眰瀹屾垚 Excel 鍏ュ簱锛歕n- 瑙ｆ瀽璁板綍鏁帮細3\n- 娑夊強璐拱鍗曚綅鏁帮細1\n- 鏂板璐拱鍗曚綅锛?\n- 鏂板浜у搧锛?\n- 璺宠繃閲嶅浜у搧锛?			2026-03-27 03:21:23.376835
7	mn7uzh8exghhvtexth	\N	user	寮€濮嬪垎鏋?Excel锛氭潨鍏嬫棗.xlsx			2026-03-27 03:22:05.702527
8	mn7uzh8exghhvtexth	\N	assistant	Excel 鍒嗘瀽瀹屾垚\n宸ヤ綔琛細鍑鸿揣\n璇嶆潯鏁伴噺锛?2\n璇嶆潯锛氬巶鍚嶃€佹棩鏈熴€佸崟鍙枫€佷骇鍝佸瀷鍙枫€佷骇鍝佸悕绉般€佹暟閲?浠躲€佽鏍?KG銆佹暟閲?KG銆佸崟浠?鍏冦€侀噾棰?鍏冦€佸娉ㄣ€侀噾棰濆悎璁n缃戞牸琛屾暟锛?0\n鏍蜂緥鏁版嵁锛歕n1. 浜у搧鍚嶇О:PU鐧藉簳婕嗭紱浜у搧鍨嬪彿:D904锛涘崟浠?鍏?7锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:9804\n2. 浜у搧鍚嶇О:PU鍝戝厜鐧介潰婕嗭紙涓夊垎鍏夛級锛涗骇鍝佸瀷鍙?D850锛涘崟浠?鍏?12锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:婢滃畤鍝戠櫧\n3. 浜у搧鍚嶇О:PU鍝戝厜鍥哄寲鍓傦紱浜у搧鍨嬪彿:D303锛涘崟浠?鍏?12锛涘崟鍙?7锛涘巶鍚?鏉滃厠鏃楋紱澶囨敞:303			2026-03-27 03:22:05.99966
9	mn7uzh8exghhvtexth	\N	user	鍔犲叆鏁版嵁搴?		2026-03-27 03:22:13.471713
10	mn7uzh8exghhvtexth	\N	assistant	宸叉寜鑱婂ぉ璇锋眰瀹屾垚 Excel 鍏ュ簱锛歕n- 瑙ｆ瀽璁板綍鏁帮細3\n- 娑夊強璐拱鍗曚綅鏁帮細1\n- 鏂板璐拱鍗曚綅锛?\n- 鏂板浜у搧锛?\n- 璺宠繃閲嶅浜у搧锛?			2026-03-27 03:22:13.579931
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.alembic_version (version_num) FROM stdin;
xcagi_v5_approval_system
f0c2a8e1_templates
\.


--
-- Data for Name: approval_delegations; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.approval_delegations (id, delegator_id, delegate_id, flow_ids, start_time, end_time, reason, is_active, created_at, created_by) FROM stdin;
\.


--
-- Data for Name: approval_flow_nodes; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.approval_flow_nodes (id, flow_id, node_name, node_order, node_type, approver_type, approver_ids, min_approvals, condition_expression, condition_description, timeout_hours, timeout_action, is_active, created_at, updated_at) FROM stdin;
1	1	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[1, 2]"	1	\N	\N	\N	notify	t	2026-04-17 03:57:48.205608+00	2026-04-17 03:57:48.205608+00
2	1	鎬荤粡鐞嗗鎵?2	serial	user	"[3]"	1	\N	\N	\N	notify	t	2026-04-17 03:57:48.205608+00	2026-04-17 03:57:48.205608+00
3	2	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 03:59:20.616521+00	2026-04-17 03:59:20.616521+00
4	2	鎬荤粡鐞嗗鎵?2	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 03:59:20.616521+00	2026-04-17 03:59:20.616521+00
5	3	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:00:21.010369+00	2026-04-17 04:00:21.010369+00
6	3	鎬荤粡鐞嗗鎵?2	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:00:21.010369+00	2026-04-17 04:00:21.010369+00
7	4	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:01:21.271307+00	2026-04-17 04:01:21.271307+00
8	4	鎬荤粡鐞嗗鎵?2	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:01:21.271307+00	2026-04-17 04:01:21.271307+00
9	5	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:02:10.866375+00	2026-04-17 04:02:10.866375+00
10	5	鎬荤粡鐞嗗鎵?2	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:02:10.866375+00	2026-04-17 04:02:10.866375+00
11	6	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:03:09.319251+00	2026-04-17 04:03:09.319251+00
12	6	鎬荤粡鐞嗗鎵?2	serial	user	"[4]"	1	\N	\N	\N	notify	t	2026-04-17 04:03:09.319251+00	2026-04-17 04:03:09.319251+00
13	7	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:04:35.546167+00	2026-04-17 04:04:35.546167+00
14	7	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:04:35.546167+00	2026-04-17 04:04:35.546167+00
15	8	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:06:48.724532+00	2026-04-17 04:06:48.724532+00
16	8	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:06:48.724532+00	2026-04-17 04:06:48.724532+00
17	9	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:08:18.215218+00	2026-04-17 04:08:18.215218+00
18	9	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:08:18.215218+00	2026-04-17 04:08:18.215218+00
19	10	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:08:47.236823+00	2026-04-17 04:08:47.236823+00
20	10	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:08:47.236823+00	2026-04-17 04:08:47.236823+00
21	11	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:09:30.958432+00	2026-04-17 04:09:30.958432+00
22	11	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:09:30.958432+00	2026-04-17 04:09:30.958432+00
23	12	閮ㄩ棬缁忕悊瀹℃壒	1	serial	user	[3]	1	\N	\N	\N	notify	t	2026-04-17 04:21:55.704435+00	2026-04-17 04:21:55.704435+00
24	12	鎬荤粡鐞嗗鎵?2	serial	user	[4]	1	\N	\N	\N	notify	t	2026-04-17 04:21:55.704435+00	2026-04-17 04:21:55.704435+00
\.


--
-- Data for Name: approval_flows; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.approval_flows (id, flow_key, flow_name, description, industry, node_type, allow_transfer, allow_delegate, allow_withdraw, timeout_hours, is_active, is_deleted, created_by, created_at, updated_at, business_type) FROM stdin;
1	test_flow_1776398262	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 03:57:48.205608+00	2026-04-17 03:57:48.205608+00	general
2	test_flow_1776398355	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 03:59:20.616521+00	2026-04-17 03:59:20.616521+00	general
3	test_flow_1776398415	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:00:21.010369+00	2026-04-17 04:00:21.010369+00	general
4	test_flow_1776398475	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:01:21.271307+00	2026-04-17 04:01:21.271307+00	general
5	test_flow_1776398525	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:02:10.866375+00	2026-04-17 04:02:10.866375+00	general
6	test_flow_1776398583	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:03:09.319251+00	2026-04-17 04:03:09.319251+00	general
7	test_flow_1776398669	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:04:35.546167+00	2026-04-17 04:04:35.546167+00	general
8	test_flow_1776398803	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:06:48.724532+00	2026-04-17 04:06:48.724532+00	general
9	test_flow_1776398892	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:08:18.215218+00	2026-04-17 04:08:18.215218+00	general
10	test_flow_1776398921	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:08:47.236823+00	2026-04-17 04:08:47.236823+00	general
11	test_flow_1776398965	娴嬭瘯鍑鸿揣鍗曞鎵规祦绋?娴嬭瘯鐢ㄥ鎵规祦绋?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:09:30.958432+00	2026-04-17 04:09:30.958432+00	general
12	shipment_approval_v2	鍑鸿揣鍗曞鎵规祦绋?鍑鸿揣鍗曢渶瑕佷袱绾у鎵?閫氱敤	serial	t	f	t	48	t	f	\N	2026-04-17 04:21:55.704435+00	2026-04-17 04:21:55.704435+00	general
\.


--
-- Data for Name: approval_records; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.approval_records (id, request_id, node_id, node_name, node_order, approver_id, approver_name, action, opinion, reject_reason, is_passed, transferred_from, transferred_to, delegate_user, action_time, deadline, created_at) FROM stdin;
1	3	9	閮ㄩ棬缁忕悊瀹℃壒	1	4	绠＄悊鍛?withdraw	鎻愪氦瀹℃壒鐢宠	\N	f	\N	\N	\N	2026-04-17 04:02:10.935621+00	2026-04-18 12:02:10.953203+00	2026-04-17 04:02:10.935621+00
2	3	9	閮ㄩ棬缁忕悊瀹℃壒	1	4	绠＄悊鍛?approve	閮ㄩ棬缁忕悊鍚屾剰	\N	t	\N	\N	\N	2026-04-17 04:02:10.935621+00	2026-04-18 12:02:10.976115+00	2026-04-17 04:02:10.935621+00
\.


--
-- Data for Name: approval_requests; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.approval_requests (id, request_no, flow_id, business_type, business_id, business_data, applicant_id, applicant_name, applicant_department, title, description, current_node_id, current_node_order, status, priority, submitted_at, approved_at, rejected_at, expired_at, approved_by, approved_by_name, rejection_reason, created_at, updated_at) FROM stdin;
1	ARSHI20260417120021D52C6F	3	shipment	999	{"test": "data"}	4	绠＄悊鍛?\N	娴嬭瘯鍑鸿揣鍗曞鎵?杩欐槸涓€涓祴璇曞鎵硅姹?5	1	pending	normal	2026-04-17 04:00:21.039953+00	\N	\N	2026-04-19 12:00:21.060728+00	\N	\N	\N	2026-04-17 04:00:21.039953+00	2026-04-17 04:00:21.039953+00
2	ARSHI20260417120121B984A9	4	shipment	999	{"test": "data"}	4	绠＄悊鍛?\N	娴嬭瘯鍑鸿揣鍗曞鎵?杩欐槸涓€涓祴璇曞鎵硅姹?7	1	pending	normal	2026-04-17 04:01:21.340649+00	\N	\N	2026-04-19 12:01:21.415772+00	\N	\N	\N	2026-04-17 04:01:21.340649+00	2026-04-17 04:01:21.340649+00
3	ARSHI202604171202102BA52D	5	shipment	999	{"test": "data"}	4	绠＄悊鍛?\N	娴嬭瘯鍑鸿揣鍗曞鎵?杩欐槸涓€涓祴璇曞鎵硅姹?10	2	in_progress	normal	2026-04-17 04:02:10.894934+00	\N	\N	2026-04-19 12:02:10.912857+00	\N	\N	\N	2026-04-17 04:02:10.894934+00	2026-04-17 04:02:10.935621+00
4	ARSHI202604171203091805BA	6	shipment	999	{"test": "data"}	4	绠＄悊鍛?\N	娴嬭瘯鍑鸿揣鍗曞鎵?杩欐槸涓€涓祴璇曞鎵硅姹?11	1	pending	normal	2026-04-17 04:03:09.367281+00	\N	\N	2026-04-19 12:03:09.411102+00	\N	\N	\N	2026-04-17 04:03:09.367281+00	2026-04-17 04:03:09.367281+00
9	APR20260419-D04BE1	12	shipment	\N	\N	4	\N	\N	鐑熼浘娴嬭瘯-鎻愪氦	楠岃瘉瀹℃壒鍐欏叆瀹¤	23	1	pending	normal	2026-04-19 11:38:34.545316+00	\N	\N	\N	\N	\N	\N	2026-04-19 11:38:34.545316+00	2026-04-19 11:38:34.545316+00
\.


--
-- Data for Name: distillation_log; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.distillation_log (id, query, intent, slots, confidence, source, created_at, used_for_training) FROM stdin;
\.


--
-- Data for Name: document_templates; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.document_templates (id, slug, display_name, role, storage_relpath, is_default, is_active, sort_order, created_at, updated_at, file_format, business_scope, editor_payload, legacy_sqlite_id) FROM stdin;
67f0f551-64d1-4ec0-ad99-e17322f1bd6a	price_list_default	榛樿鎶ヤ环琛?price_list_docx	424/妯℃澘.docx	t	t	0	2026-04-14 03:13:48.986762+00	2026-04-14 03:13:48.986762+00	docx	\N	{}	\N
30794af8-d001-4b33-9b55-a4d8bcec8157	sales_pzmob	璐攢 / PZMOB	sales_contract_docx	424/PZMOB.docx	f	f	0	2026-04-14 03:13:48.986762+00	2026-04-14 03:13:48.986762+00	docx	\N	{}	\N
08920df8-824f-4058-bc57-5ab21b7b64b7	sales_cn	閿€鍞悎鍚岋紙涓枃鏂囦欢鍚嶏級	sales_contract_docx	424/templates/閿€鍞悎鍚屾ā鏉?docx	f	f	10	2026-04-14 03:13:48.986762+00	2026-04-14 03:13:48.986762+00	docx	\N	{}	\N
dc9c9f1f-b15b-4ab4-b9c5-f0e8fc773672	sales_delivery	閫佽揣鍗?sales_contract_docx	424/document_templates/閫佽揣鍗?xls	t	t	0	2026-04-14 12:01:15.618122+00	2026-04-14 12:01:15.618122+00	xls	\N	{}	\N
\.


--
-- Data for Name: excel_vector_chunks; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.excel_vector_chunks (chunk_id, index_id, content, embedding, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: excel_vector_indexes; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.excel_vector_indexes (index_id, name, source_file, created_at, updated_at, chunk_count) FROM stdin;
\.


--
-- Data for Name: extract_logs; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.extract_logs (id, file_name, file_path, data_type, total_rows, valid_rows, imported_rows, skipped_rows, failed_rows, status, error_message, field_mapping, created_at) FROM stdin;
\.


--
-- Data for Name: inventory_ledger; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.inventory_ledger (id, product_id, warehouse_id, location_id, batch_no, quantity, available_quantity, reserved_quantity, unit, in_date, expire_date, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: inventory_transactions; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.inventory_transactions (id, ledger_id, transaction_type, product_id, warehouse_id, location_id, batch_no, quantity, before_quantity, after_quantity, unit_price, total_amount, reference_type, reference_id, transaction_date, operator, remark, created_at) FROM stdin;
\.


--
-- Data for Name: mp_addresses; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_addresses (id, user_id, contact_name, contact_phone, province, city, district, detail_address, is_default, created_at) FROM stdin;
\.


--
-- Data for Name: mp_browse_history; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_browse_history (id, user_id, product_id, viewed_at) FROM stdin;
\.


--
-- Data for Name: mp_carts; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_carts (id, user_id, product_id, quantity, selected, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: mp_favorites; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_favorites (id, user_id, product_id, created_at) FROM stdin;
\.


--
-- Data for Name: mp_feedbacks; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_feedbacks (id, user_id, type, content, images, status, reply, replied_by, replied_at, created_at) FROM stdin;
\.


--
-- Data for Name: mp_notifications; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_notifications (id, user_id, title, content, type, is_read, related_type, related_id, created_at) FROM stdin;
\.


--
-- Data for Name: mp_order_items; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_order_items (id, order_id, product_id, product_name, product_sku, quantity, unit_price, subtotal, remark) FROM stdin;
\.


--
-- Data for Name: mp_orders; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.mp_orders (id, order_no, user_id, status, total_amount, pay_amount, pay_status, pay_time, delivery_name, delivery_phone, delivery_address, delivery_province, delivery_city, delivery_district, remark, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: permissions; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.permissions (id, name, code, description, module, created_at) FROM stdin;
1	鏌ョ湅瀹㈡埛	customer.view		customer	2026-03-21 11:39:35
2	缂栬緫瀹㈡埛	customer.edit		customer	2026-03-21 11:39:35
3	鏌ョ湅浜у搧	product.view		product	2026-03-21 11:39:35
4	缂栬緫浜у搧	product.edit		product	2026-03-21 11:39:35
5	鏌ョ湅鍑鸿揣鍗?shipment.view		shipment	2026-03-21 11:39:35
6	鍒涘缓鍑鸿揣鍗?shipment.create		shipment	2026-03-21 11:39:35
7	缂栬緫鍑鸿揣鍗?shipment.edit		shipment	2026-03-21 11:39:35
8	瀹℃壒鍑鸿揣鍗?shipment.approve		shipment	2026-03-21 11:39:35
9	鏍囩鎵撳嵃	print.label		print	2026-03-21 11:39:35
10	鏌ョ湅鐗╂枡	material.view		material	2026-03-21 11:39:35
11	缂栬緫鐗╂枡	material.edit		material	2026-03-21 11:39:35
12	绠＄悊鐢ㄦ埛	admin.manage_users		admin	2026-03-21 11:39:35
13	绯荤粺閰嶇疆	admin.system_config		admin	2026-03-21 11:39:35
\.


--
-- Data for Name: products; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.products (id, model_number, name, specification, price, quantity, description, category, brand, unit, is_active, created_at, updated_at) FROM stdin;
1392	6810	PE鐑熺啅鏈ㄧ毊娓呮紗	20KG/妗?22	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1393		PE娓呴潰婕?20KG/妗?35	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1394		PE娓呴潰婕嗕笓鐢ㄦ按	15KG/妗?12.8	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1395	1870R	PU閫忔槑灏侀棴搴曟紗	20KG/妗?16.5	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1396	8022A	PU鑰愰粍閫忔槑搴曟紗	20KG/妗?15.8	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1397	303H	PU鑰愰粍搴曟紗纭寲鍓?20KG/妗?33	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1398	6821T	PE鐧藉簳婕?30KG/妗?13.8	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1399	108A	PE棣欒晧姘?20KG/妗?14.5	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1400	1870B	PU閫忔槑搴曟紗	20KG/妗?15.5	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1401	3721	PU鐧藉簳婕?25KG/妗?16.5	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1402	308	PU搴曟紗鍥哄寲鍓?10KG/缂?26	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1403	6822B	PE閫忔槑搴曟紗	20KG/妗?18	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1404	6822A	PE楂樻竻閫忔槑搴曟紗锛堟棤绮夛級	20KG/妗?20	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1405	999	PU绋€閲婂墏	15KG/妗?14.5	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1406	3706B	PU楂樻竻鐗圭骇楂樺厜閫忔槑闈㈡紗	20KG/妗?28	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1407	3706-60F	PU鍝戝厜娓呴潰婕嗭紙鍥涘垎鍏夛級	20KG/妗?28	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1408	306B	PU浜厜鍥哄寲鍓?10KG/缂?32	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1409	3706H	PU楂樻竻浜厜閫忔槑闈㈡紗	18KG/妗?35	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1410	394H	PU鑰愰粍浜厜鍥哄寲鍓?10KG/缂?37	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1411	306H	PU楂樻竻浜厜鍥哄寲鍓?10KG/缂?26	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1412	3100H	PU闈㈡紗绋€閲婂墏	15KG/妗?12.8	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1413	nan	鑹茬簿	4KG/鍗?50	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1414	nan	娲楁灙姘?15KG/妗?10	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1415	nan	鎱㈠共姘?15KG/妗?17	0	\N	\N	\N	鎯犲窞甯傛灚椹板鍏锋湁闄愬叕鍙?1	2026-04-19 22:49:09.926585	2026-04-19 22:49:09.926585
1416	3721	PU鐜繚鐧藉簳婕?20KG/妗?14	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1417	2188	PU鐧藉簳纭寲鍓?10KG/缂?25	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1418	1870D	PU灏佸浐搴曟紗	20KG/妗?13.5	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1419	308	PU搴曟紗纭寲鍓?10KG/缂?25	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1420		姘存€цˉ鍦?4KG/鍗?13	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1421		榛勮壊绮?4KG/鍗?42	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1422		搴曡壊绮?4KG/鍗?42	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1423	8828	PU澶村害搴曟紗	20KG/妗?14	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1424	6822B	PE涓害搴曟紗	20KG/妗?18	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1425		淇壊绮?鑹茬簿	20KG/妗?42	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1426	3704	PU淇壊婕?18KG/妗?19	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1427	7226-50F	PU鑰愮（鍝戝厜閫忔槑闈㈡紗	20KG/妗?24	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1428	303	PU鍝戝厜纭寲鍓?10KG/缂?26	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1429	777	PU澶╅偅姘?闈㈡按)	15KG/妗?12.8	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1430		PE澶╅偅姘?15KG/妗?11.8	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1431		鏉捐妭姘?鏉鹃姘?13KG/妗?11.5	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1432		鏍间附鏂?20KG/妗?38	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1433		鐧借壊姘存€цˉ鍦?4KG/鍗?13	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1434	nan	PU澶村害纭寲鍓?10KG/缂?26	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1435		娲楁灙姘?14KG/妗?12	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1436		PU鐧藉簳澶╅偅姘粹湕	15KG/妗?14	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1437		鍘熷瓙鐏?4KG/鍗?13	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1438	DBE CAC	鎱㈠共姘?15KG/妗?18	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1439		PU鑰愰粍鍝戝厜绫崇櫧闈㈡紗	20KG/妗?28	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1440		PU鑰愰粍鍝戝厜绫崇櫧纭寲鍓?10KG/缂?35	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1441	779	NC棣欐鑹查潰婕?20KG/妗?38	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1442		PU鑹叉紗	20KG/妗?28	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1443		涓欓叜	14KG/妗?18	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1444	3708	PU浜厜榛戦潰婕?20KG/妗?28	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
1445	306B	PU浜厜纭寲鍓?10KG/缂?35	0	\N	\N	\N	娣卞湷甯傜櫨鏈ㄩ紟瀹跺叿鏈夐檺鍏徃	1	2026-04-19 22:50:11.363373	2026-04-19 22:50:11.363373
\.


--
-- Data for Name: purchase_inbound_items; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.purchase_inbound_items (id, inbound_id, product_id, order_item_id, product_name, batch_no, quantity, unit, unit_price, amount, location_id, remark, created_at) FROM stdin;
\.


--
-- Data for Name: purchase_inbounds; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.purchase_inbounds (id, inbound_no, order_id, supplier_id, warehouse_id, inbound_date, total_amount, status, handler, remark, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: purchase_order_items; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.purchase_order_items (id, order_id, product_id, product_name, specification, quantity, unit, unit_price, amount, received_quantity, invoiced_quantity, status, remark, created_at) FROM stdin;
\.


--
-- Data for Name: purchase_orders; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.purchase_orders (id, order_no, supplier_id, warehouse_id, order_date, delivery_date, total_amount, paid_amount, status, approver, approve_date, remark, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: purchase_units; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.purchase_units (id, unit_name, contact_person, contact_phone, address, is_active, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.role_permissions (role_id, permission_id) FROM stdin;
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.roles (id, name, description, is_system, created_at, updated_at) FROM stdin;
1	viewer	鍙鐢ㄦ埛	t	2026-03-21 11:39:35	2026-03-21 11:39:35
2	operator	鎿嶄綔鍛?t	2026-03-21 11:39:35	2026-03-21 11:39:35
3	admin	绠＄悊鍛?t	2026-03-21 11:39:35	2026-03-21 11:39:35
\.


--
-- Data for Name: shipment_records; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.shipment_records (id, purchase_unit, unit_id, product_name, model_number, quantity_kg, quantity_tins, tin_spec, unit_price, amount, status, created_at, updated_at, printed_at, printer_name, raw_text, parsed_data) FROM stdin;
\.


--
-- Data for Name: storage_locations; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.storage_locations (id, warehouse_id, code, name, max_capacity, current_capacity, status, created_at) FROM stdin;
\.


--
-- Data for Name: suppliers; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.suppliers (id, code, name, contact_person, contact_phone, contact_email, address, payment_terms, credit_limit, status, rating, remark, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: template_usage_log; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.template_usage_log (id, template_id, action, result, created_at) FROM stdin;
\.


--
-- Data for Name: templates; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.templates (id, template_key, template_name, template_type, original_file_path, analyzed_data, editable_config, zone_config, merged_cells_config, style_config, business_rules, is_active, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: training_stats; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.training_stats (id, intent, count, last_updated) FROM stdin;
\.


--
-- Data for Name: user_memories; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.user_memories (id, user_id, preferences, frequent_actions, historical_contexts, feedback_history, updated_at) FROM stdin;
\.


--
-- Data for Name: user_preferences; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.user_preferences (id, user_id, preference_key, preference_value, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.users (id, username, password, display_name, email, role, is_active, created_by, created_at, last_login, wx_openid, wx_unionid, wx_avatar_url, mp_phone, mp_nickname) FROM stdin;
4	admin	scrypt:32768:8:1$H6vsT8TyBqAlg7yg$60370acc742c1c8d233c61a126011f1890588100b4fc376c137c4752f096bd174141f31bece8ad8ff7f426685eff3a10c2028ea28cf33f4dc3e52d8be83ba443	绠＄悊鍛?admin@local	admin	t	\N	2026-03-21 11:39:35.680772	2026-03-24 07:39:17.710864	\N	\N	\N	\N	\N
\.


--
-- Data for Name: warehouses; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.warehouses (id, code, name, type, address, manager, status, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: wechat_contact_context; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.wechat_contact_context (id, contact_id, wechat_id, context_json, message_count, updated_at) FROM stdin;
\.


--
-- Data for Name: wechat_contacts; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.wechat_contacts (id, contact_name, remark, wechat_id, contact_type, is_active, is_starred, created_at, updated_at) FROM stdin;
1	淇寛绉戞妧	楠楀瓙	wxid_tfxzqdqt87oa22	contact	1	1	2026-03-22 22:03:18.966197	2026-03-27 00:20:40.315225
2	钂欏.D.璺		wxid_n2vz31jvmvyg22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
3	鍗庝附鐨勮姳鐢熸秱瑁呯帺鍏蜂氦娴佺兢		18619657840@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
4	浼婅棨Z		wxid_b2zj72ljhb7z22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
5	4243342		wxid_bommxleja9kq22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
6	Sanguinius		wxid_5eyxed0ra50k22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
7	鍖楃含鍥涘崄涓€掳		wxid_nf7f2zo6x1cz21	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
8	ray		wxid_mcytvs6aatfz22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
9	鑳?铏?浠?澶?鍙?瀵?浜嗎祾岬?	xxhyilu	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
10	鍙惁鍊熸垜绛変竴鐢?	wxid_50omox95peee22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
11	201314		wxid_c29gq6zy7a7822	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
12	Jambo		wxid_22r1h5bvt17v22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
13	銆?	wxid_4zypc7vjzovp22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
14	寮犳鼎娑?	lylovezrh	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
15	涓夊浗鏉€ | 鐜嬫垬楂樻牎鑱旇禌绉嬪璧?1缇?	46163799880@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
16	鍚村浆喔咅煒赤竻		wxid_o4gw48hwu5ag12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
17	闃挎瑕佸姫鍔涘晩		wxid_v0dx054mfqxu22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
18	馃惏馃惏		wxid_wmw3odj0cefd22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
19	绁佸ぉ澶у湥		wxid_rvv1t5gxkd4422	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
20	Y Sh_		wxid_lyy3j7trfwci22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
21	涓夊浗鏉€ | 鐜嬫垬楂樻牎鑱旇禌绉嬪璧?6缇?	48218908133@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
22	澶栧崠渚?	wxid_wcgqdd2vmj0a22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
23	鑷敱鐨勫柕		wxid_mtrs3zvh54mi22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
24	闆笅鐨勬槸鐩?	wxid_duoyrrxjibxy22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
25	閫熼€熻揪澶滈棿闆堕閾?缇?	43809509622@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
26	yx.		wxid_yvbd84z4l4l922	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
27	ysh		wxid_f46sna62uvry22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
28	NICK		wxid_9zf7e0p6i4kx22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
29	Cheng		wxid_d18eeqz6c4do22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
30	Gwen		wxid_9cck4fuhtp3r12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
31	鍝堝搱馃槃		wxid_qwrue3zm707s22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
32	瀹夐潤鐪嬬湅		wxid_fujift5qpmz622	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
33	lSkJ		wxid_9nvhq4go3of652	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
34	闈炴床椴奔		wxid_98lv34xx43mm22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
35	灏忓嘲		wxid_2x2mpellc1ya22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
36	姣忓ぉ		wxid_hkpgve6xio6222	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
37	鑱仾		wxid_3ra2ilffuytq22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
38	鍏冨		wxid_cco4ocgy0gx422	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
39	澶╁ぉ绁炲埜绂忓埄鍚?	25984985661917344@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
40	銆惵锋灄鍏堟．		wxid_231esklatmn422	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
41	鐧介瓟瀵煎＋		wxid_es9gthoiuoi722	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
42	娌欑櫧楣垮師		wxid_tzni3m2g0e7i22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
43	鐪兼尝		wxid_r60gu2j4kxhi22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
44	鏂藉奖缁撴硶鍗帮綖娴侀		wxid_btty1unt72pj22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
45	澶栧崠鍒稿姪鎵嬸煣р伕鲁		25984983555624015@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
47	涓冨畨		wxid_vf3ljhfcbucl22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
48	鐧介緳椹琟_^鏉庣鏋?	wxid_x6cvsq9ao94722	contact	1	0	2026-03-24 15:07:26	2026-03-25 12:29:21.503136
49	tsuki		wxid_yc6p5grcavc822	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
50	鍏夐槾瀛樿崏鏈ㄦ灟		wxid_fkiuf7f01asr22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
51	鎴戝墤涔熸湭灏濅笉鍒煍?	wxid_vil14yixgl2v22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
52	鍕惧嬀鍝?	wxid_tv7pzogic6an22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
53	灞辨湁鐏靛叜		wxid_czmofl9glsgs22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
54	鑻ヤ笘锝炴湁绁炴槑		wxid_259xryd3rii122	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
55	涓嬪崐澶滅殑椋?	wxid_rwqv0r0qfr6922	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
56	mentoko		guaiyaerwoaini	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
57	闈掓湪绾?	wxid_9zl6kot0pwa622	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
58	2D		wxid_ovethvsq78so22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
59	馃		wxid_if5vpjkpe90022	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
60	馃悘閰烽叿鐨勭緤馃悘		wxid_mhblnaft4nmv22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
61	寮犵惃鏄?	zhangkun_3966	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
62	寮犲鑸?	wxid_lu7nbx4xdt7s22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
63	鏂囦欢浼犺緭鍔╂墜		filehelper	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
64	娆?	wxid_t5bkoyshyjqz22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
65	姊︽兂		wxid_lcbpvb5d40hs22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
66	鍏村敖鏅氬洖鑸?	wxid_ygx18yi5lmt722	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
67	寰俊鍥㈤槦		weixin	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
68	Tian鍛樺		jinzaomu309189	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
69	鐏腑鍋氳嚜宸?	wxid_ez2zql0oz8dl22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
70	鍚翠紵鐢?	wuweisheng8717	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
71	類?鏈ㄨ柉绮勷煃?	blovey4494	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
72	鑻炵背馃尳		wxid_vntw9obvxigj22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
73	AA.cat		wxid_fy4l8cpryxbp22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
74	浼嶇€氶箺		hostscan	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
75	Sn		wxid_ve0pbpn3uyw422	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
76	鍗庝附鐨勮姳鐢?	wxid_px9zydeuo8c211	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
77	鎴愰兘淇寛绉戞妧鏈夐檺鍏徃		50337179398@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
78	鐜嬪钀?	25984984815882538@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
79	鏄伆鑹茬殑杈?	wxid_k4cbck3k599r22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
80	鏉ㄥ竼		qq492211844	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
81	鍏ㄧ悆閲戣瀺澶т浆缇?	47295166322@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
82	heart		wxid_7l6u62d7kft012	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
83	浣愭墜		wxid_qqmgacc68evc22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
84	浣欓煹		wxid_57x05wbc2l6922	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
85	涔愮炕澶╃數绔炶€佹澘缇?2缇?	50573580342@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
86	鏄ュ北濂?	wxid_z1s729cmzn1j22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
87	杩滃湪鍜昂		wxid_jdncti5izoqf22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
88	鍑粈涔堜涪涓嬫垜		wxid_w2loirh6v1ut22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
89	灏忛奔鎯宠楸?	wxid_i8nzwrh9pq1222	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
90	Ccc		wxid_1ocix36j3qne22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
91	鍐扮硸钁崲		wxid_s9zcij5gzdx122	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
92	灞曟甯?	wxid_yqels1fe19at22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
93	sk8er y		zheng-740298582	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
94	鐫跨惔		wxid_59wtn7oj9zvp22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
95	鍏泤		25984985175481944@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
96	鍟ヤ篃涓嶆槸		wxid_bt2fr8sdms5w22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
97	銋?	wxid_i4qbvnaed73b22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
98	鍚涘瓙濂介€慯O^		wxid_54gznoog8iio22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
99	闆?	wxid_ur8pab0926jx22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
100	Astoria		wxid_zhm1zadg33sy22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
101	xxp		wxid_2vjofm3mm8xh12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
102	澶辫触楸?	wxid_9840268410112	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
103	X.Bao	鍖呮偊姝?wxid_olmb20sceujq22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
104	Lft鍥哄畾瀹㈡湇-灏忓啲 鏈夋€ヤ簨call锛?0-16鐐?		25984982455956866@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
105	鍗冨瓧浣?	wxid_ocw8qblkuuzj22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
106	00鍚庰煇煇磋亰澶╁惞鐗涚兢		46076608426@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
107	712		wxid_vpipdt91m6zq22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
108	fish		yujinwen1991	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
109	鍜曞挄濮?	wxid_tz0g00xpkg6g22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
110	瀹?	wxid_ffirjy27ynk322	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
111	绗簲浜烘牸蹇冨皬鏄?	25984985756261178@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
112	澶т寒鐢熼矞搴?钄彍椴滆倝鎵瑰彂锛?	loveeo5248	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
113	灏佺闄愬埗 鏃犳硶璇磋瘽 鑱旂郴铔嬫尀鏂板彿 16鍙疯В灏?	25984983446685384@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
114	楂樺懠鍚惧悕闃胯惃杈?	wxid_sdrwhmcf5atu22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
115	鍗滈儴		wxid_477vl9oglp0a22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
116	鍖搞晻		wxid_bqbtk9yiaomf22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
117	骞抽亾路鍥炲皹		wxid_c4ic9cwmgfzj22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
118	闃挎槦		wxid_mcnmipwctasr22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
119	璐濊礉閿?	wxid_3rkuey9eaxsa12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
120	Mr.Wisdom		wxid_x5s3r28dizzm22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
121	涓夊浗鏉€-妗冨瓙馃崙寤虹兢鐗?	25984985158624113@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
122	QClaw瀹㈡湇		25984991666160581@kefu.openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
123	灏忛洩		qweqwe2311111	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
124	cc	鑽ｈ秴	wxid_r9om3vs0scml12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
125	鏉庢煇		wxid_sikjy2nykqpg12	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
126	ZhangMingXi馃崅		wxid_3wu9l26xtpcp22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
127	鐜嬩竴鍚?	wxid_ee1b7lrce2ea22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
128	鏈ㄥ瓙瀹舵棌		1538519831@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
129	...		wxid_sab79xe0e88y22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
130	寮€蹇冩瘡涓€澶?	wxid_qkkiplqw8gjn22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
131	鏈ㄦ湪		xiaosen247661	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
132	鏅撳効閮?	wxid_ewnonjpbddlw22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
133	ccc.		wxid_kpwr571gojbp22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
134	銆愮帺瀹剁鐞嗐€戝皬钖?	25984983977144339@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
135	涓滆帪闈㈡潃 | 鏂板彾鍠?	25984982089014327@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
136	(;麓嗉庎憾袛嗉庎憾`)		wxid_b5h5r7xwt6pq22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
137	鍝?	wxid_iz2nhqzhkt6c22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
138	Sensei		hw1992919823	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
139	ll		wxid_m5rnm7elx3zd22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
140	涔愬ぉ鐭ュ懡鐨勫皬鏉?	wxid_oni48vdf5n0g22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
141	鏈ㄥ北浠?	wxid_yuthjznagshf22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
142	鐪间腑鐨勯偅棰楁矙		wxid_3p4dto9mj0wi22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
143	娲?	wxid_xinbq39qefbc22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
144	娈哄弸闆嗙粨绀捐礋璐ｄ汉缇?	43607342681@chatroom	group	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
145	鏃犺█		wxid_pihhjf30c5kx22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
146	瀹ｄ紶灏忕粍钖涜枦		25984985768879741@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
147	銆傘€傘€?	wxid_0y11rdvpggan22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
148	鍙嶆涓嶆槸浜哄懙		wxid_qlj355jfjesr22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
149	1		wxid_idxdmc19jnwi22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
150	娼ゅ厫		wxid_dpuglht1esn422	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
151	涔愮炕澶╁皬鏈哄櫒浜?	25984985220529570@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
152	榛樼瑱		wxid_whkhx419vr9a22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
153	Murphy		wxid_6f8e6mbo975q22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
384	5E瀵规垬骞冲彴		gh_56549cb13f6b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
154	瀹ｄ紶灏忕粍-姗欏瓙		25984985674455834@openim	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
155	鏂囪繙		wxid_n2ko09dyb0621	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
156	鏅傜┖銈掕秺銇堛仧鎬濄亜		wxid_f122efo22lry22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
157	鍏摜		flasharea	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
158	姒嗕弗		wxid_uhhtmwrdv6ih22	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
159	鍒?姹?	vipliujiang	contact	1	0	2026-03-24 15:07:26	2026-03-27 00:20:40.315225
160	鏈嶅姟閫氱煡		notifymessage	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
161	鍛ㄥ懆		wxid_6966ezdc7jjx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
162	鍗虫椂璁捐浜х爺鍗忎綔骞冲彴		gh_3472e6c66785	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
163	鏄庢偊鐪奸暅瀹夊窞鍩庡競瀛﹂櫌搴?	wxid_c17f57o8yrm812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
164	luma ai涓枃绔?	gh_59f4562282fb	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
165	A鍗栫數鑴戙€佺洃鎺х殑闄堟不鏄?3730702211		wxid_1552985532712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
166	宸濊秺娴峰场		gh_84a3d8dfb402	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
167	鏉ョ數鏈嶅姟鎸囧崡		gh_4f0ce2be4762	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
168	鍗虫椂璁捐JsDesign		gh_4accc57a1b9e	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
169	瀹濊棌铓婂瓙鍚?	gh_0c84658a807b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
170	灏忕數		gh_15afeb1f47c9	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
171	琚佸18628276389		wxid_ckalr04qhrp912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
172	闀挎床		wxid_g2lx9svdxe7541	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
173	鑱斾紬鐢佃剳绉戞妧鏈夐檺鍏徃		wxid_hppehgrmpg4u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
174	鑵捐闊充箰浜哄皬绉樹功		gh_bcf78433d969	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
175	闈炴⒌鏁磋瀹氬埗-浣曟帉鏌?	wxid_hkzpifny599k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
176	绗戠湅浜虹敓		wxid_l2sntxq2eofj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
177	缁甸槼甯傜涓変汉姘戝尰闄?	gh_721f44d52617	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
178	灏忕嫍闄櫔		gh_88f24c7ceaa0	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
179	鍏勫紵		wxid_g60lmasnlg6922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
180	闈?	wxid_h7dpqtbxzjbj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
181	渚簹鏉?	wxid_8603546038012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
182	鍗佸叚		wxid_s5fuvl7kj7ms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
183	馃槄		wxid_00utmh6e4nr522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
184	闀跨泩璁″垝		wxid_1vrv634a61gw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
185	A鍗囧瑙勫垝涓€瀛欒€佸笀		wxid_1nvcx79nymry22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
186	鏉庣亸锛堟繁鍦宠挋鏂】瀹跺叿锛?	wxid_5e9i347d9kf321	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
187	賰诃诰賷賵蹏		wxid_2rceaei93y7e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
188	寰俊杩愬姩		gh_43f2581f6fd6	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
189	鍚埅鑰冪爺鍒樿€佸笀13408167100		wxid_hunlrw6jg6sb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
190	閫椾箰鐨勬煚妾?	wxid_14dvsghqde5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
191	鐜嬭€佸笀馃キ		wxid_au5sx1iailno22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
192	L涓?	lprnarajjang	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
193	铚€鍏夎仈鐩?	gh_c485012e0fc5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
194	鑺稿鐨勭敓娲昏		gh_1e509004ef4d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
195	A鏅村ぉ锛?0-24鐐瑰湪绾匡級		wxid_c4cjwz2i0vea22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
196	灏忛檲		wxid_pm9yusn86hm822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
197	鏈€寮烘墜娓稿繀鐜?	gh_22cbcceedb20	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
198	濉?鏅?鏂板獟浣撳闀?wxid_oszb57bt8vqm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
199	涓浗澶у鐢熷湪绾?	gh_219cc6412594	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
200	鑵捐浜戝姪鎵?	gh_a73e2407e0f8	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
201	寰俊鏀舵鍔╂墜		gh_f0a92aa7146c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
202	涓浗閭斂		gh_488675187ff5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
203	鍥涘窛鏃ユ姤		gh_8c1381e0f694	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
204	璇ヨ处鍙峰凡娉ㄩ攢		gh_0f813977a8bb	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
205	闀垮畨涓囦竾骞?	wxid_xin73etckqoh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
206	璐﹀彿缁存姢锛岃鍏堟坊鍔犲鏈?		wxid_9x0degk9zvb522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
207	绯栧彂鍙?	gh_86bcc44defa3	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
208	涓浗寤鸿閾惰		gh_a19f4d5e89e5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
209	蹇冪诞蹇冪悊椤鹃棶鏉滆€佸笀19136302102		wxid_ldsl0xz086db22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
210	鍗氭€滱IPPT		gh_ac376bc51a95	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
211	璐点亰&	娼囧	wxid_orhwhxi8if2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
212	鑵捐鎴愰暱瀹堟姢		gh_0465b03f4e70	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
213	Ayw		wxid_87q3y5tu2n6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
214	澶хAPP		gh_52c1a6df0ae5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
215	Echo璁捐鍔╂墜		wxid_rwwa1ikb6mne22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
216	鍢垮樋		wxid_0vk73ozxeoft22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
217	绂忓缓鐪佸皧瀹濇瘮钀?	gh_ec1fd77905cd	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
218	just do it		wxid_4imugt6q92lm12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
219	鎵弿鍏ㄨ兘鐜?	gh_31f9fce2127e	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
220	婊?	wxid_k4nvx3vs2un422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
221	岐?嗑€嘟?铔笉璁叉潕濂冲＋嗑€嘟?岍め瓟		wxid_tarhnqqe0a7s21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
222	鏅村ぉ瀹㈡湇锛堟病鍥炲灏辨槸鏈変簨鍦級		wxid_itg6yjs4u9jr12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
223	C~c		wxid_e27nbtu1hl6t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
224	缃戞槗钘忓疂闃?	gh_1c3fc24db685	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
225	鍝╁竷鍝╁竷AI		gh_315e955abdf5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
226	11.0.11		wxid_46uq1matx8fg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
227	娌佸窛浣?	wxid_qvr4dl3wncaa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
228	鍐欏瓧鏈?	wxid_fxfr8kppzdml22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
229	wjp		wxid_tpldjjfju30x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
230	鎴忔槬宸?鎴忔槬宸?wxid_vppj6ygkm5cc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
231	鍦嗛€氶€熼€?	gh_9963baf9ea78	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
232	澶忓ぉ鐨勯		wxid_anrusn3xqnma1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
233	鏈嬪弸鎺ㄨ崘娑堟伅		fmessage	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
234	璇煶璁颁簨鏈?	medianote	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
235	婕傛祦鐡?	floatbottle	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
236	鑵捐瀹㈡湇		gh_402d777f217d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
237	鎷煎澶?	gh_79dda79128bf	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
238	鍥涘窛鍗氱墿闄?	gh_19489cb139ff	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
239	鎴愰兘甯傞噾鐗涘尯鍗忓悓澶栬瀛︽牎		gh_50e608af6e7c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
240	鎴愰兘澧ㄩ噷鐢诲		gh_fe1d43444653	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
241	鐮嶄环缇ゅ姞鍏ヤ簰鍔?	gh_62409b4e3e05	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
242	浜掑府绀惧洟		gh_38f848223b5a	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
243	浜掑姪缇や阜		gh_a9d61cc43cd0	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
244	姣忓ぉ鏀剁背		gh_12e97e71f23e	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
245	寰俊娓告垙		gh_25d9ac85a4bc	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
246	缃楄嫢浼犲獟		gh_08df50827306	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
247	鎴愰兘鍗氱墿棣?	gh_bb4c663a4093	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
248	鑿╃挒鑺辫崯缂?	gh_c0b2429362d8	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
249	鐧介┈鑺辩敯钀ラ€犵ぞ		gh_2b087e71d011	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
250	鐏岀楂樻墜姝ｇ増鎺堟潈鎵嬫父		gh_15a248d88953	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
251	鐖辫挷AIPU		gh_78b33c7d4da4	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
252	瓒ｈ鏁欒偛		gh_2d4a15fade66	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
253	涓夊浗鏉€绉诲姩鐗?	gh_2a26b909d7c8	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
254	涓夊浗鏉€灏忔父鎴?	gh_eae7a8ca6a7c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
255	褰辫糠鍏富		gh_8414cd5718c6	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
256	鐑堝叕鏂囧寲		gh_5c2ea6302b16	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
257	濂芥父蹇垎APP		gh_8059dc244661	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
258	鑺卞弻褰辫糠		gh_fff1166d63f6	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
259	鍥涘窛澶╁簻鍋ュ悍		gh_14c0c6c5d3dd	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
260	鎴愰兘鍙戝竷		gh_fe0bed5299b9	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
261	涓婚鏁欏		gh_7850c6d36d76	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
262	37鎵嬫父淇变箰閮?	gh_6cc26361d86d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
263	鎴愰兘楂樹腑瀛︿笟鎴愮哗鏌ヨ		gh_f89d5e2ff6b4	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
264	缇ょ瀹跺伐鍏?	gh_084524249265	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
265	涓夋槦鐢靛瓙瀹樻柟		gh_16b946b21fd0	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
266	鏄撳閫?	gh_bb9be961595a	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
267	钃濆ぉ		wxid_auwq89iz7ykg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
268	灏氳鍑虹増骞冲彴		gh_6a06b07d7a5d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
269	鑷敱婵€娲荤爜		gh_c0e969b2a7e1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
270	褰撲笅缇庤偛		gh_7386e5cd0ce8	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
271	浣撳僵绔炵寽		gh_aeacf22e0d11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
272	缇庢湳鍙?	gh_0fb9a8bbc4f5	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
273	ZK789鎷涚敓鑰冭瘯淇℃伅缃?	gh_1484b5debe5b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
274	鑵捐绂忓埄楣?	gh_4c4447c751dc	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
275	浼犱俊灏忓姪鎵?	gh_ac6fb8cf2e6d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
276	绠€鍒橫BTI		gh_98994671c9b2	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
277	鑵捐鑷€夎偂寰俊鐗坾寰瘉鍒?	gh_c2c60e9dddd9	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
278	涓浗绂忓僵		gh_cdbbf51c70b4	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
279	鑹烘湳鐢熸动瑙勫垝		gh_6a67dac3ecd0	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
280	鎴愰兘鏈湴瀹?	gh_adde58601f8c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
281	瓒呮椂浠ｆ櫤鑳借亰澶〢I鏈哄櫒浜?	gh_51e398eda0d9	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
282	寮瑰３鐗规敾闃?	gh_c52360b53d08	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
283	搴旂敤瀹濇父鎴忕鍒?	gh_b9450bcdc771	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
284	鍗庡鍩洪噾		gh_3fccf62186ce	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
285	鍥涘窛鐪佹暀鑲茬瀛︾爺绌堕櫌		gh_27bbfc32c689	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
286	寰俊鎸囨暟		gh_45fc41cd8fbb	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
287	闃冲厜楂樿€冧俊鎭钩鍙?	gh_ce765f64941f	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
288	璇ヨ处鍙峰凡鍐荤粨		gh_e1e8df755135	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
289	楂樻嫑鍒嗙瓟		gh_31393190e1b3	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
290	鍥涘窛鐢靛奖鐢佃瀛﹂櫌灏变笟鎸囧涓績		gh_a32f2526860f	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
291	鍥涘窛鐢靛奖鐢佃瀛﹂櫌鎷涚敓灏变笟澶?	gh_dfa3306bbdac	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
292	閿﹀煄鎷涚敓		gh_cafb42a1ebd0	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
293	缇庡洟绮惧搧闆嗗競		gh_c77a6d6cb83b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
294	鍥涘窛鐪佹暀鑲茶€冭瘯闄?	gh_8c427c82fa24	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
295	鍥涘窛鏁欒偛鍙戝竷		gh_a6b5da9f59a1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
296	绠?	wxid_j64td7ipig6222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
297	safe鏍″洯		gh_b651c3b3d91b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
298	缁甸槼鍩庡競瀛﹂櫌鏅烘収鏍″洯		gh_581739df944c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
299	鑼剁櫨閬揅haPanda		gh_f8f471f133f8	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
300	缁靛煄鍥句功棣?	gh_262fd48e8d4d	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
301	澶╁簻鏂伴潚骞?	gh_d6b534528ff1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
302	宀涘矝鐚?	gh_4084f60a07e2	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
303	鏁欏璐ㄩ噺绠＄悊骞冲彴		gh_a4e4c1df2209	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
304	鍒涙剰鏄熺悆缃?	gh_84d4658f6a45	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
305	涓€浜嬭澶╀笅		gh_fdf63c507115	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
306	Echo璁捐瀹濊棌搴?	gh_ef6153148769	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
307	浜哄伐鏅鸿兘鏉鹃紶		gh_60b60a773b17	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
308	鏀堕挶鍚ф牎鍥鍗?	gh_04f319b6cc25	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
309	缁靛煄鑴卞崟		gh_20107c837381	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
310	姹夊牎鐜嬩腑鍥?	gh_1f8eebff0348	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
311	涓滀笢鐢电珵淇变箰閮?	gh_7e97de94ca41	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
312	涔愮炕澶╃數绔炰勘涔愰儴		gh_af3f2a8923d7	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
313	馃數		wxid_9p2p4lcr0xug32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
314	9		wxid_n05obqcwut0w12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
315	鎭枩鐧艰病.		wxid_wdxutk5g9ajk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
316	AI鐖辫緟瀵煎皬鍔╂墜		gh_6abc6da28e41	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
317	NEKO		wxid_y3xyi4ubpk5g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
318	闈掕悕鎴愭辰		wxid_qzmtqqpuq5c522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
319	浼氳灏忓紶		wxid_zy43kyyiy6ox12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
320	璁捐|鍥伴毦		wxid_2l9l552qcz1922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
321	瑙傜墿瑷€璇?	gh_af088478b8e9	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
322	Bae.		wxid_k781pkroubf022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
323	鐜嬮挦鐢?	wxid_rkvxbyzygvsu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
324	涓冪楸?涓冪楸?wxid_fvs2urbkfa7222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
325	浜庢笖娓?	wxid_pokzdik0j5dr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
326	浜戞贰椋庤交	馃尫鐜嬸煂锋馃尫鏄?w58294150	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
327	鎶栭煶蹇墜鐩存挱馃憫 杩喀		wxid_nus8iphxlpd122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
328	姊ㄥ槈鏉?		wxid_j3sejugd1bp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
329	-涔勮┖-		wxid_sb9sz90knoho22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
330	涓嶅枬鐟炲垢		wxid_q39i4r2sbjpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
331	鐖辨厱		wxid_vusiijj8ckwl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
332	z.		wxid_4nb8tsqrjqtu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
333	26		wxid_z68cnwvjrsxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
334	zhang		wxid_3ijl0zlax62912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
335	涓夊叾		wxid_k8lvomzn9gvm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
336	楣胯宸锋祿鑼?楣胯宸锋祿鑼?wxid_54uff7iokfwi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
337	AIPPT		gh_e30cfc5e880b	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
338	.		wxid_p0yb817ruqp622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
339	钀濆崪		wxid_a9im1agi94jr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
340	馃槴馃槴		wxid_6qva3wg5bnb912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
341	cookie dough		wxid_c9nr81ozpky022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
342	绂呰尪鏄搤鐜嬭鑰?	wxid_z1ds19zvas1m21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
343	coconut		wxid_63dzfvdpv0x822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
344	绗戠湅浜虹敓		wxid_z89lyb4oge9x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
345	嗉掄繄嗉權緡嗫堗紥		wxid_8mdg0yreypgz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
346	queen	鏉庢墠淇?wxid_uwvt09bpx4nl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
347	妲愯姳闄㈣惤闂叉暎浜恒€?	wxid_5iorf40750yn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
348	缃戞槗瓒呯骇浼氬憳		gh_1b0144d05edf	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
349	ZZZZT		wxid_oh8yz5el3ty022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
350	YAN		wxid_rnpq0g648sie22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
351	馃悘馃馃悜		wxid_e7f7oyu03ba012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
352	hxyw	hxyw	wxid_4rm1c0xm0bjk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
353	澶у獩鍎?	wangyuan1450719729	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
354	AA-铚€瀹夐┚鏍★紙鑰冨満鐝級		wxid_qzucv9rggxs712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
355	馃崣馃崣		wxid_2g0wo314yvd129	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
356	鏂楃綏澶ч檰榄傚笀瀵瑰喅瀹樻柟		gh_e22fd7e8607c	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
357	AA鐩涘ぉ浣撹偛褰╃エ锛堣娆炬墦绁級		wxid_69vnd9eqzz2l12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
358	灞?	wxid_qvacl2tr2tgp12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
359	7ince		wxid_0bykhu8ox75n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
360	鏈煇戝崄涓?鎴存辰宄?wxid_ifeie0kp9d9u12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
361	ayo_nakiiovo		wxid_xxi82tfbz3un22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
362	缂?	wxid_0dksxfa1huls22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
363	s.		wxid_gk8qeuzapstq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
364	ThnXiY		wxid_z14cq49cmhil22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
365	鐜嬫捣鑾?		wxid_nfgz3jtia2xb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
366	灏忓		wxid_t7i920vmesrv32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
367	lostendercar	钂嬬▼浜戞捣	wxid_iutxa6lfft3o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
368	闃垮疂		wxid_ryweohgwauq221	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
369	bloom	0	wxid_0owtal34zreg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
370	鐣欏０鏈?	wxid_6f2duzi2khz332	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
371	瀹夐噷娼?	wxid_vbn8w7g10b9h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
372	蹇冪诞蹇冪悊妤氭鑰佸笀15680418372		wxid_sdhz19jkhl6622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
373	浣犳渶鍙痠		wxid_bkamfv3i2lj422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
374	澶忔辰鍏?	wxid_cqihh2fa5j2v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
375	24		wxid_sa0kwi5poiih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
376	36姘垱鎶曞钩鍙?	gh_590a6b91475a	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
377	M媒		wxid_kz6y0e0sthrs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
378	鍙樻爲		wxid_rl5muuaetx7812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
379	HOosky.		wxid_cq711b6ecj5g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
380	璞嗙煡		wxid_264g835pxqut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
381	涓冨挷閫?	wxid_izl07q467die12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
382	姗樺瓙		wxid_7qop7o3qtb9422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
383	D5瀹樻柟		gh_36a4ddedb519	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
385	銋?鍒樻槗閾?wxid_e00z3rq03kcs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
386	鑹粩		wxid_8604jbrsahi822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
387	娴侀€?	wxid_f87odkqgj1si22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
388	Life is a dream.		wxid_lb6tc0ir5bm222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
389	幞煂濁瓌缃掑馃挅		x801226	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
390	鎯冲幓娓镐箰鍥帺鐨勫皬鍏矾鍐?	wxid_ihcrzzrc60nb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
391	瀛欒仦杩?Creative Inventor		wxid_hi5k0x8o3uls22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
392	鐑堢		wxid_i9gpku7o4omf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
393	馃崟	@........	wxid_bu5zoh1hf2k022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
394	寮犵櫧鐧金煂?	wxid_kt14xacw1q8o12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
395	馃檭 馃檪		wxid_whhzhcc9xyls22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
396	Justine		wxid_p2tm5x1g9fbz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
397	A.浣撳僵.鍏泭鏈嶅姟锛堜綋鑲插僵绁級		aj317979405	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
398	n1	涔栧効瀛?wxid_xn53g6cmnfj022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
399	Muver		wxid_e1lsqc464sad22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
400	s andw		wxid_5a8j70kfsdu612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
401	楸?	wxid_0d892mm1zs2o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
402	娼福		wxid_74v7c7gr5von22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
403	涓夊浗鏉€涓€灏嗘垚鍚?	gh_26d689d1f5b2	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
404	楹嬮箍		wxid_kp2vkqah9n7821	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
405	璧汯ing		wxid_z6rlgo9cj2tk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
406	鑿插効		wxid_abtl1r71yp2v21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
407	yoyo	鍟靛暤鍙絶.	wxid_cgtq0q5nwjpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
408	娴呯伆钃漗O^锛?	wxid_9p1rowewgnd822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
409	缃戞槗UU鍔犻€熷櫒		gh_cfb3533bbdda	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
410	鏄庢偊鐪奸暅		gh_76ec1f13b590	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
411	椴佸ぇ甯堜細鍛樻湇鍔?	gh_0abbd13997b4	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
412	鍏ㄥ浗澶у鐢熷垱涓氭湇鍔＄綉		gh_9631b9d04f7a	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
413	榄旈煶宸ュ潑鏈嶅姟鍙?	gh_51675e125628	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
414	鏅舵櫠鑰佸笀		wxid_vunda1kwwwl912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
415	鎵规敼缃?	gh_11ec9c4428e1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
416	HAWKST		wxid_o0k2niqehxm122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
417	鏉滆€佸笀		wxid_3727954106012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
418	AIG鐜悆鍔ㄦ极娓告垙鍗氳浼?	gh_6553aef75a60	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
419	ASUS鍗庣鏈嶅姟		gh_38f0f2b19dcd	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
420	寰俊鏀粯		gh_3dfda90e39d6	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
421	钖泂ir		tt5620	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
422	CGATLAS		gh_b076f119bf9f	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
423	甯堣€?鏂芥稕閫熷啓		wxid_f2f9fzsle5zn12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
424	闈掗潚teacher馃構		wxid_h6qfy91j3zyq12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
425	鎺㈤浘		wxid_k4zugkn6tky722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
426	鑱婃枊		wxid_1lbveea6th3b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
427	鎴愰兘澧ㄩ噷鐢诲		wxid_8buytyqhyvzw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
428	澶у笀鍗?	wxid_ep4yugoj6lzd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
429	鏅撳€?璐﹀彿宸插仠鐢?		wxid_ho10fbom0i9722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
430	銆?	wxid_igv6a74zha4k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
431	鏄熶箣		wxid_sh9pyz71axi422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
432	鑹捐枃鍎?	wxid_uhu0o29o0mlm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
433	Jack		wxid_vynqyy4dob5a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
434	榛勫啲鑻?	wxid_y53b4o84zoya22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
435	Echo锛?	wxid_kta7jnphbd6t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
436	EE		wxid_pnzuf9jzt8gz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
437	Amme		wxid_n0wfi0g3jje022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
438	闃跨惓	闃跨惓 闄堜繚鏋?wxid_ost39afu2jd422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
439	SORUA		wxid_j9xtp9lk0jm822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
440	馃崝		wxid_xx9hhf9uj2yn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
441	銆屾捣闇炪€?	wxid_7cqg26o9pdbz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
442	榄傚湪婢冲ぇ鍒╀簹~_^		wxid_n2l0qof9hqf322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
443	Ex des1n馃導		wxid_m9l1urfuypms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
444	鎰氭垙	鎰氭垙	wxid_im31gwljeew522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
445	绉︽槦浜?	wxid_n8l49q6pz5qw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
446	榛勬枃鏉?	Jesuncc	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
447	鍋跺伓鏄釜濂藉コ瀛?灏辫繖涓?wxid_im7klmil3rlc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
448	R1NA		wxid_9jdivvmzlhz622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
449	HH.	HH.	wxid_renyzb0azjzd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
450	涓嶈兘娌℃湁鍐扮編寮?	wxid_ghhlctrn6irf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
451	X		wxid_j6g0gfbod54722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
452	涓€蕰 岬斸触岬?蕯澶?	wxid_8r387pr8oa2f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
453	鍙剁殑绗節绔?	wxid_savj1y7y0x5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
454	eden*		wxid_uojgok3gijwy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
455	333		wxid_lfacpfwa8ql222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
456	寮ユ暒閬?瑗挎补濮愬	wxid_07ph0z681box22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
457	涔夋槑		wxid_e7zv78blz0y422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
458	姝﹂瓊娈挎枟缃?03鍖?	25165380838@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
459	鏅氭櫞宸?	wxid_91xrovsvkp9k12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
460	wxid_ejfbi6q9pxpm22		wxid_ejfbi6q9pxpm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
461	涔︾嚂		25984985439552734@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
462	b绔欑鍒╁畼-fufu锛堝伐浣滄椂闂达細9:00-18:00锛?	25984982665547956@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
463	褰辫鍚庢湡-璐鸿€佸笀锛?2灏忔椂閫氳繃锛?	25984982605771502@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
464	瀹夌惇		25984984679408311@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
465	瀹樻柟灏忓姪鎵?59锛?:30-娆℃棩1:30锛?	25984984447782240@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
466	灏婂疂姣旇惃-绌烘皵瀹濆疂		25984984499137995@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
467	5EPlay瀹樻柟鍙?	25984983449755680@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
468	瀹樻柟灏忓姪鎵?60锛?:00-娆℃棩00:00锛?	25984985303299625@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
469	寤鸿寮犻鎬°€愭湇鍔′唬鐮?2070271銆?	25984985737167022@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
470	绗簲浜烘牸灏忓姪鎵?	25984982390891887@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
471	绗簲浜烘牸灏忓姪鎵?	25984985234141369@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
472	绯栧彂鍙?鎶€鏈敮鎸?	25984982780879605@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
473	OurPlay灏忓姪鎵?5		25984983195933497@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
474	澶╁缃戞父		25984982976856317@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
475	澶╂触鏍℃姎鍙?瀹ｄ紶灏忕粍-鍏姳		25984985145009489@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
476	鐜嬪€╂枃		25984982468383285@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
477	鏉庢ⅵ		25984985414422054@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
478	寮犵惁		25984981918103170@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
479	鍥涘窛鎴愰兘鍙屾祦浼樺搧閬撳簵		25984981668496630@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
480	灏忔▕-鍥炴敹绂忓埄瀹?84		25984983915268224@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
481	灏忔▕-鍥炴敹绂忓埄瀹?39		25984985789819265@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
482	涓夊浗鏉€-妗冨瓙瀛﹀1馃崙		25984982400304339@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
483	涓夊浗鏉€-妗冨瓙瀛﹀2馃崙		25984982170723102@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
484	LFT鍙戝憜:22-04		25984985881024387@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
485	鎶栭煶鐢靛晢杩愯惀椤鹃棶		25984983507436120@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
486	鏉庢竻		25984982057567840@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
487	灏忔噿2.0(姝ゅ彿涓嶅洖澶嶏級		25984983438205460@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
488	涓夊浗鏉€-妗冨瓙1馃崙		25984982386743703@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
489	涓夊浗鏉€-妗冨瓙4馃崙		25984983243243743@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
490	LFT鐐圭偣閰别煩靛皬闆?	25984984504513831@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
491	灏忓姪鎵?	25984981912758087@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
492	绗簲浜烘牸灏忓姪鎵?	25984983451851500@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
493	瀹樻柟灏忓姪鎵?13		25984983279799424@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
494	瀹樻柟灏忓姪鎵?64锛?:00-娆℃棩1:00锛?	25984983338557326@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
495	涓夊浗鏉€-妗冨瓙8馃崙		25984982367856099@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
496	涓夊浗鏉€-7妗冨瓙		25984984325203725@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
497	瀹㈡湇锛氳崝鏋濓紙鍒偓鍗″彿16-22		25984983092299140@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
498	濉旀柉姹€ 鈥?涓浗姹夊牎锛堝畨宸炰簲璺彛搴楋級瀹㈡湇		25984985583217338@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
499	娆ф皵鐩茬洅鎯呮姤绔?fufu		25984984556862884@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
500	澶╁ぉ绁炲埜绂忓埄鍚?	25984982513478005@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
501	褰辫鍚庢湡-钃濊€佸笀(12灏忔椂閫氳繃)		25984983145684779@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
502	瀹樻柟灏忓姪鎵?24锛?:00-娆℃棩00:00锛?	25984982365691558@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
503	澶曢亣		wxid_3hb8qsip8u9h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
504	鐜╁鍥?| 灏忕伀榫?	25984981855179160@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
505	缇ゆ椿鍔ㄥ皬鍔╂墜-鏃犺█		25984984698411801@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
506	鍜曞櫆椋橀鎷?	wxid_62fom1q40jvs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
507	鍑屽窛锛堟槸鍟婂窛鍟婏級		wxid_8120421205312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
508	閰烽叿鐨勭伀鏌?	wxid_d4ucl7kdf93822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
509	閭楅殢浜?	wxid_adca7n8tbbqp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
510	unlock		wxid_vta0smcndd9r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
511	DT鍦熻眴		wxid_wg0zqil9aa9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
512	鍒樺垬澶ч『		wxid_w9evxqb6wg4a12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
513	闀挎灄鍚洦		wxid_3jablcpsx93522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
514	aaa骞绘兂澶ц繍姹借溅甯堝倕		wxid_lk33eph1228v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
515	Y		wxid_05u0engq4qjq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
516	瓒呯骇鏃犳晫闇哥帇榫欚煢?	wxid_oyo43rtpmi4u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
517	鍗楃繆		wxid_p96y7tvmiop22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
518	鍥涙湀		wxid_117w68qpx0r822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
519	缇婂窘寰?	wxid_wdhlqc6gh5p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
520	姘挎⒌嗉?	wxid_1smmbgi9m27212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
521	Sagittarius		wxid_pwuzqm1pdghf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
522	娌?	wxid_snaue1ju1s8h32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
523	鐙肩帇		wxid_lehw0f0a722c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
524	銉愩儛銉堛偣		wxid_wri6vazgtcyk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
525	鎴戞€庝箞浠€涔堥兘涓嶄細		wxid_nkxj0b77wsoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
526	绉嬬櫧鍑岃緵		wxid_xh6ucplbcaor22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
527	绉欐湻		wxid_b2g54trwjhp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
528	God among human		wxid_j4f0qkx9n1au12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
529	sleeplesssssss		wxid_eqqd930jvn3b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
530	鐖盓LYSIA		wxid_ogad1o9bs84e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
531	灞辩緤		wxid_5udienul56cz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
532	鎴戠湡娌℃嫑浜?	wxid_9p4vd9farfiu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
533	鏄熸槦		wxid_xc9cf7qc5y3e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
534	瀛欐棭鐫○煉?	wxid_jsgm49ucikne22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
535	m璞?	wxid_swykjz8eboud22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
536	闄堜韩		wxid_ies68aby5vlf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
537	鐚笌绉嬪垁楸?	wxid_382fe7efkgh822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
538	銋?	wxid_wxne23fhuyvi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
539	Heaven		a33039605	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
540	11		wxid_27pq1lrc8dib22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
541	杩呴浄涓嶅強鎺╄€崇洍閾冨効鍝嶅彯褰?	wxid_y9awhh3w1y6f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
542	钁ｆ暚鐢?	wxid_wp7qrk4qr4ie22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
543	鏍€娓?	wxid_z7gfpud0xbyh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
544	xiaodu__dada		wxid_jium7cn7p9ox12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
545	灏樺焹钀藉畾		wxid_7qhnogww5w3u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
546	澶ц懕鍗风厧楗?	wxid_ycb3cags7vlm32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
547	闄屽皹		wxid_borq269m1vad22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
548	鍏ㄨ兘閰挄鍚?	wxid_q5rb7vom26eh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
549	鏋冲.		wxid_vieyqq5rfyw122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
550	閲忚鍣?	wxid_d2u97a04xpcy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
551	銆傘€?	wxid_dpw9q5oxdd9422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
552	姣忎竵		wxid_npua5h0oxcp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
553	骞婚噺		wxid_bjcli7dbge0d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
554	銆?	wxid_xch13hqroy6m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
555	Venti		wxid_vyb9r2u7yb7s22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
556	闂工		wxid_hcxwpoxl5c5d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
557	wzn		wxid_pne4012v026m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
558	浣曟墍闂昏€屾潵锛屼綍鎵€瑙佽€屽幓		wxid_fxe7dfw310bg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
559	灏忛奔涓嶇煡閬?	wxid_pf0dhdj86hcc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
560	head shot		wxid_otz8kjy0a4d112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
561	闃冲厜寮€鏈楃殑鐢峰		wxid_ah4i6o4a0a1t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
562	鐏板ぇ鐜?	wxid_8z3mioe2v8se22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
563	鏉ㄦ煶涓嶈闂槬椋?	wxid_kq4ax1bxip0a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
564	鏂潶绂忔ˉ鐨勭帠		wxid_066mcb5qv6t122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
565	鏉庡竻		wxid_8w1xuq4d955k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
566	鏉€浜嗗畠娌＄尨瀛?	wxid_4w1glzfur86m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
567	鐜?	wxid_xp2h9buii3di22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
568	Mario		wxid_zvi75tc1a2d822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
569	娼樻櫒鏅?	wxid_lnbgtmoek53v12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
570	棰?	wxid_9o2vknrphy9u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
571	Yellow Rain		wxid_8m11angijghp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
572	涓夌鍙?	wxid_c9vacpsp8ng522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
573	DJ濂藉儚		wxid_927q5vdx6wzm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
574	浜庣煩		wxid_4tgk1tb8ccvf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
575	婕㈤杸姹熸按		wxid_brbtrlzyl05n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
576	灏忕伀杞?113		wxid_wq950s9p4yhb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
577	1ii		wxid_ay5sywjkwszz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
578	琛屽垪涔嬫瓕		wxid_kts91t4cfg0q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
579	娓呴鏉ㄦ煶宀?	wxid_6x4hbsjsjlpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
580	浣曞		wxid_jyj96fzranzw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
581	娲诲湪褰撲笅		wxid_eqbwwr5cwxkg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
582	Shiho Miyano		wxid_4i41w1u1edz622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
583	澧ㄧ爺鑼楀悰		wxid_2v24n87ki7jk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
584	鑹惧反鍟?	wxid_oiz1vz8xhelc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
585	澧ㄧ窘鍑屽ぉZzz		wxid_tege7pm0q62922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
586	寮犳枃杞?	wxid_ummkghcsd67522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
587	鏇︾帠鑼椾綐		wxid_ftx85ft37x6f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
588	闆ㄥ康鍐?	wxid_g74d1i6psyy322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
589	娓呰僵.		wxid_e2n27eqjff3122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
590	蹇?	wxid_ynmd7bv1qbj022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
591	榛庣殑浜岄噸濂?	wxid_56oatjxuqhgp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
592	36521478		wxid_r88fmxrhkepg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
593	X.		wxid_4o4z33da5b7822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
594	娲诲湪褰撲笅		wxid_t2udub4vhlms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
595	姒?	wxid_ztyxd1qg1s7f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
596	R&K		wxid_ifj3ddzut7ne22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
597	濮?	wxid_2p6koeriqg9u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
598	榛勮€?	wxid_2f05dzo981a322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
599	鏍¤€佸紵		wxid_a3x764060vzj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
600	褰掑幓鏉ュ叜		wxid_j1oysj33ssta22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
601	閲囬噰涓葛煉氭坊鍔犲娉ㄦ潵鎰?	25984984335693441@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
602	銆愩€?	wxid_xbqoxsyhum0q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
603	鍖楃噴		wxid_lmzwley3ypvc12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
604	鎵€骞?	wxid_lpqcadkwx55k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
605	鍖呭瓙馃挕娣诲姞澶囨敞鏉ユ剰		25984981706294074@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
606	1%		wxid_zmj6msmsiahs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
607	銋?	wxid_fdj3u78weoie22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
608	鏃堕埡榫?	wxid_hyq1qryxndou22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
609	鍝﹁眮		wxid_4mb6rrb0rbq622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
610	zdtyn		wxid_ticsjkoybgxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
611	鎵岀舰鐏叞鐧藉嫼绫崇敯鍏卞湡浜?	wxid_85oho5l2yv5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
612	绁夎壇		wxid_5yf8vd9p6c3822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
613	瑭?	wxid_l16n3c1ivpv222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
614	鍝ュ竷鏋楁潅楸?	ct20061215	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
615	娓告爣鍗″昂		wxid_ofrmcpcj166922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
616	骞荤┖绌虹┖		wxid_m37jm48m4a5d11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
617	six		wxid_a5u8k6dz8wre22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
618	锛?	wxid_qo8ep0syabfg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
619	銆傘€傘€?	wxid_0bxcyn2b894e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
620	鑷敱鍥藉缁勭粐锛圤FN锛?	wxid_u8rrbb4o9d7f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
621	The Fraud寤惧尭		wxid_rsapkezvpa9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
622	瀛╁瓙鐜嬶紙娴╂旦锛?	wxid_v37tt1obb3vc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
623	銋?	wxid_33wkg5r93l3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
624	swz		wxid_zbnoxu35nooh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
625	Cloud		wxid_i88dg3jf93x822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
626	杩?	wxid_vv0xzfktrwir22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
627	瑭╄繙鏂?	ly782962035	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
628	鏍熻尪琛椾笂鐨勬潟鏉?	wxid_8spepl35d1h212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
629	绲箒		wxid_wpq2bqg0udb622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
630	鍐?	wxid_8k3nhvd2i5e722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
631	馃尭		wxid_ptrcz56a1x7822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
632	鐪奸噷鎬绘槸浜櫠鏅?	wxid_bv0siotbydgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
633	涓€鍙彯褰撴瘺		wxid_lqcuusv6nt2o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
634	鍔涘井浠婚噸涔呯鐤?	wxid_lzjmhndhyb3122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
635	m855a1		wxid_7i2k9avdqmmi12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
636	锛岋紝锛?	wxid_a96xlsn1kca022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
637	闄靛矚		wxid_l863p7inl6uq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
638	娉扮劧灏忕泦鍙?	wxid_9m7hmdj1en6m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
639	闅剧煡		wxid_xo5i00qgt8vp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
640	鑺滄箹~璧烽		wxid_yoa3grlalncl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
641	璋撹		wxid_9webbeu490ii22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
642	鐩涙箾婧?	wxid_qnxc8ioh3ghp12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
643	灏戜富		wxid_uxwwq1tj2yrr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
644	Daniec		wxid_5dd9ptnm5rx422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
645	鍒濈懢鎱曟€濆勾		wxid_bmlkwjrvz1lc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
646	闅忕紭&濡傛ⅵ		wxid_e8o35t387tcl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
647	鏄ユ睙鑺辨湀澶?	wxid_lygxyai9wew822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
648	蹇冭瘽		wxid_04a5bwrdxzd722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
649	椋庤疆婊氭粴浼?	wxid_sbpv6m88hd6229	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
650	娌変笌娴?	wxid_u6a525neo8si22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
651	nknmn		wxid_zyvp834k0uo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
652	姊wq		wxid_r1h32mp9inh822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
653	.		wxid_qcv88d4ipq9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
654	澧ㄥ叞杞荤窘		wxid_sg0pke3ebhon22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
655	馃懁		wxid_qfzfxmzkthoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
656	璋ㄦ厧		wxid_ep1ojsg611k322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
657	寮犵敳宄?	wxid_pdqg2rzm2xjx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
658	鍐滃涓€纰楅		wxid_ady8mus4ftyd12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
659	娓岃殎		wxid_ntkek4n7jej422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
660	寮?	wxid_nkshlpw054q622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
661	澶滃崕闈掍箤		wxid_of64y0td1tbf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
662	鏅?	wxid_fw8ft6u0pqli22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
663	璁鸿瘉		wxid_83r0dx780ev622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
664	閱夐厭鍦ㄧ洓鍞?	wxid_47lg7s4xepyk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
665	槌熼奔		wxid_rvrkbp878isk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
666	Jack鏇?	wxid_tw9lgf0m3o0322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
667	馃憘馃徎		wxid_aqvmm4c7cpih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
668	姣忎釜鏈堜笉鍚冭棨妞掗浮灏辨槸涓栫晫鐨勭伨闅?	wxid_m5yhurbtyoxa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
669	浜洪棿骞歌繍|锝ハ夛渐锝€)		wxid_ibr6o7n5ltsx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
670	涔旂憻澶?	wxid_tti3gu3ogaen22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
671	鍛ㄩ緳		wxid_pml86bhliapg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
672	Liu Can Do		wxid_v1jci22imcz622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
673	鍏冲北闅捐秺		wxid_n27at5b1v4cf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
674	鍗楀北		wxid_ajk531jnzeyd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
675	deAN		wxid_zhj7k2a6lfkd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
676	閫?	wxid_vkt44c74g4cf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
677	Karl		wxid_406fjasknvzw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
678	灏忔澃		25984981768034763@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
679	鏉ㄥ痉鍙?	wxid_912qbcg2k7g322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
680	(銈?銈?銇ゃ儹 骞叉澂~		wxid_ttvw1pmqkysx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
681	绁炲ぇ鏍?	wxid_w097573u6di822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
682	濞伮峰畤瀹欐棤鏁屾垬绁?	wxid_sc85plgzyysk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
683	zjt		wxid_xb7ndqeyh25x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
684	鍐囦害		wxid_zv6j6qadeor522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
685	o		wxid_ugs52osfpcfq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
686	涓冧竷鍒潵浜?	wxid_jm6wocqsyo6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
687	鎺㈢储		wxid_kmsm7qncwpoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
688	宀佹湀涓庡厜鍚屽皹		wxid_4r57xi64jloh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
689	wangkang		wxid_unxgmfz97z4k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
690	涓嶇槮涓嬫潵涓嶆敼鍚?	wxid_jq7oh0s7jxx422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
691	芦侃(*麓 涓嶊挸鍋?`*)鄱禄		wxid_ow299c6ryc4h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
692	鐭ユ湰蹇樻湯		wxid_w5fw97pl2kt722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
693	鑽よ崵		wxid_oxvlq82c90a022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
694	鍑屻伄宀?	wxid_7k415mcevwfd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
695	瑁翠笉浜?	wxid_4ogj9m593zut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
696	鍏?	wxid_1lz2ifft655q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
697	SkrArk		wxid_7r2xgz22ujlm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
698	馃敟馃敟		wxid_xnv27eqxitfg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
699	鐑績甯傛皯寮犻奔鍝ヰ煇?	wxid_3olt0og3r9g622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
700	i^^		wxid_0sagisrfa09e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
701	嗉亨綄嗉€嘟夃讲瀵傕純嗉€嘟戉蓟		wxid_ddz4ix8s20kd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
702	浣曟剰鍛?	wxid_u12vpevk05rs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
703	澶╃窘		wxid_pw776dft4xih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
704	[娼淽		wxid_u96yywhakixu12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
705	瓒呯骇鏃犳晫鏆撮緳鎴樺＋		wxid_h08lszpe8z8u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
706	銋ゃ叅銋ゃ叅		wxid_dekddosnlql222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
707	鍚冮ズ瀛?	wxid_ri8w7omxuz2122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
708	姊?	wxid_5y28r5lh44qp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
709	鐑?	wxid_yqt31zwxnune22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
710	姹熷崡		wxid_ekzbszj91avm21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
711	馃尗 [Shocked][Shocked]		wxid_wrzk70rhg34122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
712	澶╅棶		wxid_5n2rau0ioewv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
713	鐚窘闆?	wxid_90mi6sp9yoiu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
714	lll		wxid_kzqgvfaywm5g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
715	16鈩?	wxid_miflker58ce122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
716	浠婃湞骞村崕		wxid_yue6x3pqt0e422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
717	娴睙娌?	wxid_wji34kgz3ufw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
718	妫懢		wxid_mm9trdj9tlug22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
719	澶╂触楗块		wxid_rqdwwk46urtq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
720	椋庡惞瑙ｇ紮瀵?	wxid_d5kess6y5pt322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
721	涔版姤鏅撹瀹?	wxid_mdejlyk307k322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
722	绋艰僵銆?	wxid_sfagathm888822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
723	榻愬ぉ澶у湥瀛欐偀绌?	wxid_5t6urr6yfprv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
724	鍠у殻		wxid_mf6bmv5ki6fg12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
725	hbk		wxid_qmh7zjtzhsvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
726	杩愮甯峰箘		wxid_vmjzg82i5wtx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
727	澧熻建缁堢剦		woyunizhijian	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
728	姹熺憸鐧?	wxid_ya1jjn0q3f1622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
729	鍒樻湞鏃?	wxid_ro9gvafgs63e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
730	epiphany		wxid_60y7jcbjyaqc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
731	涓嶄細瀵艰埅		wxid_75pqnzbiukm822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
732	鍔悍		wxid_y91amzgoqpoh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
733	涓や华缁?	wxid_kzjciyephfod22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
734	Niuuu		wxid_1vyi8ay4kx0t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
735	銆愩€?	wxid_p8d4l0dzz1h922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
736	鏈堝奖鐤忔		wxid_wl38u1o0dfa322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
737	鏅氭湪娼囨絿		wxid_03lxiweay0an22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
738	WZP		wxid_wwa2iucoe29k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
739	niebol		wxid_s2i8tehii30n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
740	銆傘€?	wxid_9nafesd1x3vz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
741	smiley		wxid_su34xssuzmb922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
742	鏇茬粓浜烘暎		wxid_y2t34m4x2ec222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
743	鏄熺儸妫?	wxid_k6g6x3l8wolw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
744	鐏崕		wxid_7yq9psonwkwl12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
745	Miao		wxid_e6aubv7e9ix132	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
746	Hhhyf		wxid_q3eo533fct9722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
747	鍫傚悏璇冨痉		wxid_adp4nrp0th8122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
748	灏忓柕		wxid_klohvv4a5j2i22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
749	绛夌浉瑙?	wxid_efs4l2kyydx822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
750	涓€浠嬸煍?	wxid_h5tfqnd2084u12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
751	涓€钀?	wxid_g06mz034co0022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
752	鍦ㄤ簯鏈垫帉蹇?	wxid_b6ubhtgbh6l622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
753	脳		wxid_ioh10xgxil6222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
754	淇濈敓		wxid_ctaxcc9trugc12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
755	闅忎究浠栦滑鎬庝箞鐪?	wxid_z4s5rcp4lbwp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
756	銋ゃ叅銋ゃ叅銋ゃ叅銋ゃ叅		wxid_x3iobda0ll0q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
757	A		wxid_n6vpbzve9fyk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
758	鏉挎牀馃尠		wxid_q0jfkupik8fg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
759	鍥涙湀涓€鍙?	wxid_rj4hngvjckkq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
760	+1+1		wxid_vbicrf3s5aqw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
761	蹇箰濂芥兂浣?	wxid_kp11vudc2flc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
762	鑺辨棤鐥?	wxid_b4b6duicwngj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
763	闃熷弸鐨勪笁鐐规姢鐢?	wxid_sjzqeigi311q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
764	閫?	wxid_k2rl8kden67m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
765	鍝€娲汼ama		wxid_uqfjfpqlp20422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
766	you never alone.		wxid_j04kb5tfev4422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
767	鍙搁┈浼?	wxid_rjye1bzko4bd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
768	鏃犲悕		wxid_9lrn2nq1ha6m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
769	鑽€璋?	wxid_erl3pbkzvg4429	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
770	鏇规檹		wxid_y5lgmez04ise22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
771	Relieve馃尶		wxid_dzuqegn10xum22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
772	璐㈢灏忚窡鐝軎酷瓌		bao---zi	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
773	LFT瀹㈡湇楹昏柉锛?6-22锛?鍗楁瓕		25984982626823317@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
774	LFT-涓冭蒋-濞变箰		25984982692893354@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
775	LFT搴楅暱锛氱豢璞嗘矙锛堝吇鐥呬紤鎭腑锛?	25984982804023930@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
776	LFT-鍥哄畾瀹㈡湇 灏忓嚚锛堜笂鐝椂闂?2-4锛?	25984982835474458@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
777	LFT娴佸姩瀹㈡湇锛氫紭浼橈紙鏆傜锛?	25984983241200792@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
778	LFT 灏忓Ξ 椤跺皷		25984984186849727@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
779	LFT璐㈠姟		25984984542220091@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
780	銆愮鑱岀増銆戝彯鍜?	25984985384113845@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
781	婧毊銆?	25984985606337784@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
782	LFT瀹㈡湇榛涚帀锛?0-16馃崶		25984985860047038@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
783	涓夋湪		wxid_mtachjlbebag22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
784	鏃兼棩澶嶇弶鏃?	wxid_mmx6lfxzi13v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
785	鐐歌柉鏉?	wxid_rvtriqw0p0bg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
786	銋ゃ叅銋ゃ叅銋ゃ叅銋ゃ叅		wxid_4vu6vymof1to22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
787	楦＄背鑺别煡ゐ煃?	wxid_9zj3tnijjo6212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
788	鑽旀灊绌烘皵鍐?	wxid_fy3acfbp7ax822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
789	Caesar		wxid_26jyx9x818nb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
790	Stephen Curry		wxid_ilcyappxfeka12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
791	L		wxid_v0h0njq98plc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
792	瑾?	wxid_vrc5we4a7h0322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
793	閭ｄ竴骞存槬		wxid_53v3qqjql1gj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
794	銆?	wxid_pv6wdb3wh8kt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
795	szy		wxid_l0l1m4uj4u8k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
796	寮犲皬浜?	wxid_agjf7ajgleo422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
797	Loexuan-1031嘟侧紜嗑€蔀		wxid_28y3lof3vrli22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
798	鍒濋洦鍒濋亣.		wxid_1ab923wu9bft32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
799	绔犻奔鍝?	wxid_969iamv2fhxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
800	鏂戝竷鏂?	wxid_yhsqwdg7as8h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
801	cwniong		wxid_06xpygow1st012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
802	澶х鍛€馃樁		wxid_bn0pui33oo2l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
803	.		wxid_dx37kraoxfnr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
804	馃Ζ		wxid_aeha6igc829122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
805	鎼炰簨楣?	gaoge344563	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
806	灏忛奔		wxid_x8x2l4ewnmj412	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
807	娼?	wxid_jo6sdtvu29v622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
808	m		wxid_qbigth81hnr532	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
809	z		wxid_v13wqlhfujdo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
810			wxid_e7rkv6q3d2n822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
811	Plan B		huhaozheng002	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
812	Z		wxid_2ubl5flhoh6221	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
813	闄堟妯?	wxid_e71qppu0jmqf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
814	鎬€浠佸競濂藉徃鏈轰唬椹炬湇鍔℃湁闄愬叕鍙?	wxid_wzgu4px6zrgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
815	瀛愯但		wxid_6rowzyw4ryg222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
816	澶村儚灏辨槸鏈汉馃惏馃悕		wxid_gf1w3bzjtv8h12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
817	閲戝ぉ鍙堝緢鍦嗘弧		wxid_90u2otmap6b922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
818	鏆撮緳鎴樺＋		wxid_vi26uvn7aliu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
819	锟?	wxid_2i9o5a313snb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
820	娌?		wxid_phva2ayj5ie722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
821	Niko		wxid_jwycrzb0w1l921	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
822	绁炲鐨勫晩娆煒?	wxid_w0jq93432trb21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
823	涓嬬殑琛€		wxid_4wd8ycbfsc9122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
824	锛?	wxid_5mlha8rbffoh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
825	椋庡線鍖楀惞		wxid_tmbfby2exrbs21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
826	钁夋箻鍊?	wxid_aengo0wiqsr512	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
827	馃嵍		wxid_0c1m0x7zavvp12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
828	PX顎LL		p383774971	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
829	:		wxid_8376653766712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
830	Thesens		wxid_hjkv2w6j0feu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
831	绀?	lavedr	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
832	涓€鍩庯紙娉夊窞浜屾墜鏈猴紝涓嬪崍2鐐圭潯閱掞級		wxid_u0v16dha7wen12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
833	銆?	wxid_fqw46fn624aa12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
834	Jeremy Ward馃帲		wxid_45omi29bqqhi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
835	tear		wxid_zkkit1zec77m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
836	Sukairain		wxid_hxxphhv3k8lp11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
837	A绾㈡渤寰愭皬褰濋婧愰楗湁闄愬叕鍙?	wxid_moad27ed18q221	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
838	鑽?		wxid_oifbuz8v57sr12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
839	Jeffrey.		wxid_xucohylbi2f022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
840	铦庡瓙鑾辫幈		wxid_kjh1e9979gd112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
841	楠氱尓馃惙		wxid_bt9wmsqawjzt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
842	xl路Y路		wxid_qkk54sorc2k322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
843	Zxin.		z947087750	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
844	.		wxid_b8niiaf3imde21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
845	銋ゃ叅		wxid_wvgrcv59ak6t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
846	yulosi		wxid_r3j38tbbgehf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
847	椤惧＋		wxid_3txx6j2vbxpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
848	鐖卞枬鍐扮編寮?	wxid_n8f9pk72utde22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
849	.		wxid_w53mujn0b5ud22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
850	娌夌		wxid_svw5i1h49ef622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
851	X		wxid_mjiauk7rgq8122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
852	Insects awaken		wxid_odox04lbaquj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
853	COMMUNE 骞诲笀庐绋嬪痉鏉?	wxid_gehub4ykkokq21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
854	鑽?	wxid_t8jagjmf9dtu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
855	Yanni		wxid_h6zphv8b3dgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
856	槌勮帿鎬?	wxid_o1a9gr77crnb32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
857	鑷湪瀹夌劧		wxid_mchhusxz0kg212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
858	A.馃閮芥槸娴簯		wxid_zuda5ctq12ms12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
859	榛勬补闈㈠寘		wxid_i77i9trv6ta319	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
860	iss		wxid_m8txtwv9j4zt32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
861	锟撮洦		wxid_2b5kudql3k0a12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
862	L		wxid_nqm3ov9ie72s12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
863	鎵嶇枏瀛︽祬		wxid_p6fhr9jjy7gc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
864	.		wxid_4cbywya3h2p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
865	瓒呯骇鏃犳晫灏忓帀瀹?	wxid_yett0ouiccz312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
866	璋堝厑璐?	wxid_sxiyxyaoyphf32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
867	鏇?	wxid_td6ztujtbjft22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
868	ikkk		wxid_vm20htjsjld822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
869	Yzzz		wxid_q61alfq17aen22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
870	闄皬鍙夎涓効		wxid_wv8h0n3isqpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
871	ffs		wxid_p63mzi5ob1e422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
872	JNL.XG		wxid_yr1k9c2a4fso22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
873	釢瓣珱戢€戟?	wxid_8voeigfkzv522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
874	鐫¤澶у笀		wxid_mekl2j9xrekt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
875	SL		wxid_amm2mohhlqt022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
876	07star.		wxid_f62aup7o0h5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
877	璐潯銇尗		wxid_u0biljxj5wrr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
878	7811.		wxid_xjjfrk15533522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
879	闄?	wxid_fgkobzlw0qug22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
880	Aurora		wxid_5y19xa2qibrf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
881	鏈熷緟閬囧僵		wxid_fficnd3d3s7v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
882	AJLS		wxid_rsrkyifqnuio22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
883	妞?	wxid_9vup1rp4fngc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
884	涓€		wxid_644koq5wsami22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
885	鐜涘崱宸村崱		wxid_zf93667iva7v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
886	prtend		wxid_sfchu8q7w5h222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
887	鑴嗗急ok缁?	wxid_bdb6iaxhxpnu12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
888	stf		wxid_ahwcvcwvf89422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
889	鐭㈠寳		wxid_n66faaeme0c522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
890	妗旀		wxid_g6ogljjj9yxa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
891	娌℃湁鐑熶害鏈夎姳		wxid_ibk9qctnjcx122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
892	钂叉捣涓?	wxid_ujykyq0a35ny22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
893	.		wxid_58zkm00buewi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
894	銆?	wxid_docz98y1mr2o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
895	鐙挀瀵掓睙		wxid_v1b1l28zs4sl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
896	鑼曟効		wxid_wwr4y2opwwfq12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
897	black.		wxid_rzel7b7hxez622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
898	馃彅		wxid_ycgcatqtnlsk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
899	Forced laugher		wxid_usrrxsgh5v4722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
900	娓╂按鏉忚彍		wxid_lvcgeyhet7rs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
901	鍊掕鏃?	wxid_1kdg8iddwps422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
902	瑙佽闈?	wxid_qamso3txi8bt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
903	闆ㄦ穻娣?	wxid_rhfqc4uy8kn122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
904	shiomi=san		wxid_o8jqyfegdllp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
905	娴烽€?	wxid_zb6q72vqn45q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
906	loveless		wxid_844oot9v1j6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
907	骞绘湀		wxid_rxdwo4zlaar522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
908	蕗岽€纱散岽?	wxid_oqot2tyi5iu922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
909	鍝?		wxid_bsinpe79mby711	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
910	涓嶅悆棣欒彍QWQ		wxid_m3vaxmwhhhdr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
911	3yik		wxid_qxsofy5ugfqm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
912	涓嶇煡閬撹捣鍟ュ悕鍎裤€?	wxid_ggu5jodd8k6622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
913	鍐犲嵖		wxid_8pb9t5m6f4gm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
914	鏄畤涔熸槸馃悷		wxid_q3jdk7kxh2zk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
915	鏉ョ偣杩愭皵		wxid_pjor94hapc7f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
916	瀹夐潤		wxid_drsesrtyjx6222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
917	涔濈鍗佷簲渚垮＋.		wxid_zdtam68ylv8b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
918	馃崐		wxid_psesqfhb8d4e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
919	馃毞		wxid_nnm0xa4h4b9h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
920	鍓戝叞		wxid_y5dafmk53cv622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
921	闀挎槦		wxid_3w61opn8r8ya22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1080	M155		wxid_se4t9bhkxqhf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
922	濂忛熆鍥涘銇ⅷ		wxid_bgguwnw228rf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
923	娴崕涓€涓?杞灛鍗崇┖		wxid_wznynd3leyho22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
924	dawn		wxid_ba260h25bxih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
925	鍡摷		wxid_m4vtjxstsi2f12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
926	Kn0ck		wxid_ple8udsb5os122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
927	涓撴敞鑷凡		wxid_exc3dety0hny22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
928	娴佸厜		wxid_t2acc0lxikl222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
929	Ffff		wxid_vlnbilorfmi122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
930	戢涥獞嘟缄珋戢€榷鈦吧?	wxid_yn65g9198i3l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
931	Roi		wxid_48i280plnbdl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
932	Vetovas		wxid_0utas093t1do22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
933	S瑟薀岽嚿瘁礇		wxid_5rfflx20b9ee22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
934	kanade		wxid_2408khlmf8c522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
935	hu		wxid_edmhh6jz3j4d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
936	鎮蹭激骞寸硶		wxid_gej01xs2btd122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
937	鎹傝€冲惉椋?	wxid_wn8hfk6v6tat22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
938	妞板瓙鏈夊ぇ钂?	wxid_wjcm6rn2hbw222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
939	銆?	wxid_8iyrnxzqcc2v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
940	Solo.30		wxid_5omz3bll0ks422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
941	DIAMOND		wxid_wuisbxe4tva922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
942	鑺?	wxid_dd5lblhpq3sy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
943	littttt		wxid_c64aiq6vimqs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
944	鎻芥湪		wxid_nl5nsefg858822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
945	灏忔灄		wxid_xegj2pu9r2bg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
946	缁婂€掗搧鐩?	wxid_f3dm6y00lj9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
947	1QQ:o		wxid_kyfd5bnw3aju22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
948	lauv		wxid_ej3t8a6pcvz322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
949	瀛ょ櫧		wxid_esswyvxc9p1j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
950	Nice2Cu- 鎭?	wxid_s4iyzaqb0ju622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
951	鏈夌殑鑱?	wxid_d9zdwdp1jh8y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
952	Aurora		wxid_v397ls071gyu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
953	涓?	wxid_mkosowydiriu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
954	寮犳稕		wxid_h5qf3ccmvjh522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
955	銆?	wxid_ezneka0sdlms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
956	澶╂渤		wxid_nstyo708hbq222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
957	钀藉湴鏍圭敓		wxid_ruipg2nxdojk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
958	l.		wxid_fku8gduyyjlc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
959	鑰佷汉涓庢捣娲嬸煂?		wxid_lwkd5nsczusk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
960	闆伄椋?	wxid_xowufq6yz4xh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
961	X銆倄		wxid_gwrk2ghzupny22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
962	馃挔		wxid_x998190d7yuz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
963	袨谢械谐		wxid_m9yxo4ti19kd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
964	瀛ｅ讥浜?	wxid_38ust1hyhg7l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
965	涓€鍙皬鏉緓u		wxid_3b2ecosved0322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
966	馃崝馃崝		wxid_7weugmkdvgxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
967	鍗挎湁鎰?	wxid_sdd82ezp9lw821	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
968	Serein		wxid_9aq3z03svw6f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
969	Snow		wxid_na0wajnowto22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
970	D.		wxid_kpm9yiryi49r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
971	瑷€韬瀵?	wxid_tlqagp4lv0u322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
972	lovecd		wxid_a56ckv39oc9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
973	銋ゃ叅銋ゃ叅		wxid_z7nlsgeow7g922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
974	灏忚€佽檸馃殌		wxid_rz6l4mswvzw422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
975	Azir		wxid_olou3smxx8dv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
976	闃虫槬闈?	wxid_5wt754gifdwb12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
977	闆ㄤ竴鐩翠笅		wxid_tkh15z3vi8e422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
978	Coisini		wxid_iiyvjt3jfqm522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
979	璐板９骞村啲锛堟€ヤ簨鐢佃仈涓嶅€燄煉帮級		wxid_y2iezmlsyt2f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
980	榛嶇		wxid_rkx8qu5flsi722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
981	涓€骞存崲鐧惧勾		wxid_c7ilg849t7io22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
982	Shawn		wxid_uunxtiimm8q922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
983	鎮稿姩@M		wxid_3ghfz87mqzme22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
984	宀氶潪钃?	wxid_03f1e7oorcjk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
985	REN		wxid_i3fdq7eo741321	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
986	鐏姳		wxid_xxjxyvbld4lc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
987	姹愰&deg		wxid_v1akuhjj1va622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
988	CC.		wxid_0v6tg9rohfgc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
989	zzzzysssss		wxid_129s4andszs122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
990	AAA鏈嶈璁捐鍒樺摜		wxid_aignxwhii9lg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
991	M_		csfj74108520	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
992	19		wxid_n4wl3hi7u6n822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
993	Habibi		wxid_kqerpn10cgdv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
994	馃寖		wxid_pa2e97tb3zt022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
995	USA VER259 WSB		wxid_omyzy2nkpx8b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
996	榛?鐧絶~$锛?	wxid_orjpb1yjllj022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
997	妲戞灄鐏?	wxid_4iw7tikhlovm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
998	.		wxid_z8dhz4ernuhl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
999	闃垮康		wxid_88vc7hc1i2rv31	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1000	钖涘畾璋旂殑闄堟煇浜?	wxid_ab8097zwg5mf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1001	娴じ灏忓厛鐢?	wxid_tda49phi3hw522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1002	濡傛涓€鏂?	wxid_cfll7lgjukfm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1003	-_-		wxid_374rs83b940t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1004	鑻忋€?	wxid_moonw126v0t422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1005	鐖卞悆棣欒彍		wxid_x2tuvxltto8b21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1006	濂ュ埄濂?	wxid_5ejs19bk640n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1007	娌?	wxid_6yuegxnmnv0d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1008	Hear		wxid_9iqw4jd1igc222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1009	閲嶇		wxid_s0ei7dogir9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1010	鏈ㄦ槗		wxid_agiqzholerut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1011	Eblana		wxid_klkxts496q6922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1012	灏忎綍寰堝繖		wxid_pjne4l6wtyu922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1013	c-澶╄鍋?	wxid_gbybk15u87qt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1014	涓嶅繕鍒濆績		wxid_ng89wn8x3kdy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1015	璋㈣阿		wxid_soxry0f8cjib22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1016	瀵规柟姝ｅ湪杈撳叆 ...		wxid_w2j69ws3e2o422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1017	......		wxid_ihyellbmm5sl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1018	S		wxid_7zlliae3qju022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1019	鎭曞繁		wxid_p6nmtlsnbiwy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1020	灏忕唺瑕佹棭璧?	wxid_sj08xkzegkek21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1021	涓€鑸矾杩囦笁濂藉競姘?	wxid_dfbat5enf6eu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1022	鎽囧厜		wxid_hx25h2h2332c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1023	TiAmo		wxid_thls7p2ej0ax12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1024	浜ㄥ緱鍒╃殑鍛介		wxid_g8ohzabws84422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1025	绗?	wxid_6wfodu2yknja22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1026	锛堬細		wxid_nofxo4p1wayh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1027	Anemok1ng		wxid_avbiyshesjm532	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1028	濂旇荡鏄熸捣		wxid_rq5y10ityfj012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1029	hello		wxid_b0a3by1o2mlp12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1030	鐜夐閬?	wxid_0kh572vg36ta22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1031	PRAY FOR ME		wxid_cqpu8s1orad112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1032	鏄电О锛?	wxid_le0qrxq6gf3122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1033	鍏堢敓		wxid_8j41dcrqptnb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1034	鍓嶈		wxid_3q9jdxssf5t422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1035	鏈潵鍗￠敭		wxid_t53gzno784r522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1036	鍠绘枃娉?	wxid_olkutdxoak4h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1037	軎?	wxid_67ijmowvgbod22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1038	pluto		wxid_2ff51yr5b1ok22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1039	AAA寤虹瓚鏉愭枡鎵瑰彂灏忛倱		wxid_v4ep40v73ukt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1040	绉嬭緸		wxid_cla6vv6qzl3u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1041	W		wxid_rg687ybsoww422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1042	鏃烘椇澶ф潕鍖?	wxid_dvj3cjsb7vhv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1043	瀛樹竴鐐规櫤鍟?	wxid_u04kg2xgcsc522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1044	SICDATC.30		wxid_xp4w0cqhei4a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1045	馃		wxid_p4qkcg6ajjh822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1046	Ustinian		wxid_y5i4poc3dxro22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1047	銆?	wxid_joxsnvxbsj0g12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1048	Ha		wxid_icikbr6tyjzm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1049	馃挱		wxid_46i79bjfn28l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1050	閭靛皬绂诲		wxid_vy1ycra5vr2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1051	littlepig		wxid_g6adevvdl92v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1052	鏄ラ涓嶅彧鍗侀噷		wxid_21bp9kfgt4dy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1053	閵?	wxid_i7bc3msz1b2c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1054	涓夋棳鏄?	wxid_pqdjltx9jsa022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1055	鎴戠殑鍗楀北澶х帇		wxid_vhqd7e77dhm222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1056	(雸坃雸?		wxid_jrq6dvnngk2522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1057	626		wxid_850z1l2aizad22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1058	銆?	wxid_jrdoieq0woms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1059	AAA涓嶅彂鑴炬皵鍙彂璐?	wxid_ajcaccu3cawf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1060	闊﹀凹鎭?		wxid_86ebvd3lh2bm12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1061	钀?	wxid_xrj67jsp7umb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1062	0.2鈩?		wxid_574elmbyjwwv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1063	17.		wxid_mtze0a7167hf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1064	鍖楃含31掳		wxid_qkknj4hrvz8k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1065	闊彍澶х帇		wxid_oic1r9nyz9je22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1066	soul		wxid_2x9zhynw18m222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1067	涓冩湀		wxid_42rpbp8bsden22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1068	E=hv-w		wxid_1ju43m53ryt722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1069	鍔卞織璇?	wxid_wmqjb7u58kka22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1070	閽熸剰		wxid_rpxa05ez9ak322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1071	ZhangWei		wxid_2f806peb41cs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1072	浣欍€傘€?	wxid_a622cu0sxsp922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1073	浜戠幇娴烽浘宸?	wxid_kj6fyg65j89u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1074	鍐棩闆?	wxid_dok1x0awyuk622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1075	浜堜綘		wxid_jnhowye8cjwb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1076	Lolosama		wxid_mmr7h3lz31mv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1077	绁?	wxid_e5ia4c8bcemo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1078	娆?		wxid_3w1a4z7nxf6w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1079	锛氾細锛?	wxid_wz4u8x7qahd822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1081	鐣濈ū		wxid_99fl3q271y9n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1082	lip		wxid_yzwzkagkxpdr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1083	鍋氳嚜宸辩殑鍏?瑕侀€嗛椋炵繑		wxid_fk1325wfhdb622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1084	鍚冧笉楗辩潯涓嶉啋		wxid_4n2yezpxwj8122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1085	鐖卞枬鐧藉紑姘?	wxid_k00utrsssuf322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1086	灏忚揩鍌?	wxid_dbrb3tb700a322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1087	The World		wxid_2j09yadew5hv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1088	A楣忚景鏁扮爜-绮惧搧浜屾墜(缁甸槼鏁扮爜鍥炴敹)		wxid_b903lqro8vut12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1089	鎲?	wxid_qgb531g5ye4h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1090	Yopbsn		wxid_40krhws3egf322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1091	闆?	wxid_8w0i8yfh4gxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1092	shiy		wxid_iksh3i2s1xzt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1093	DAIYONGFEI.锛堝鑲岀増锛?	wxid_4gfdctm2ru4a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1094	濡?		wxid_535nqurfcphb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1095	CLAY		wxid_jbv308rfmnbj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1096	缁欎綘涔扮摐瀛?	wxid_7dy3gkdy530422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1097	Koi		wxid_ckquahdb3vmy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1098			xiaojiu507091	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1099	馃惏		ww2070181	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1100	MatchBox		PK491331163	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1101	寮犳稕		wxid_d318sk7zzvp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1102	鐑績甯傛皯缃楀厛鐢?	wxid_m1pq85u09aa322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1103	瀛ｇ尽妫?	wxid_pf05l46e51ne22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1104	LH		wxid_oa6hzd82xx8u21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1105	wxid_2mlhhpiztaq612		wxid_2mlhhpiztaq612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1106	灏忚煿		xiejian3315201	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1107	馃挦閽堝厛馃惓		seeong	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1108	澶曞嚜		wxid_w0gmcojtrb2v31	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1109	鍢夊槈鍢変辅		wxid_sir44sj4sy0322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1110	瓒婂姫鍔涳紝瓒婂垢杩?	wxid_neq9fhl8fhhb12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1111	ggggg		on262826263	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1112	鑸掑績		wxid_db950ei17hqm12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1113	ZL		wxid_cuieg32yp2q622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1114	鍙兂鎽搁奔		wxid_doswr5yfhjk622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1115	绂荤绂?	caoyi709372	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1116	寰喓鐢峰		piercing1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1117	鐖嗙偢绯栶煉?	wxid_9cjevmy1i1j421	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1118	鐜嬭鲍鎭?	wxid_y3zyaj0zhff321	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1119	钁?		wxid_ewq7z56i0rgw12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1120	椹介┈涓嶈垗		wxid_a0q1io2a97xh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1121	ba		wxid_jskn1gmjmy4h12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1122	寮燨wen		wxid_dlmz6ie7x6dv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1123	Nine Bao涓?	wxid_y38nsji1dzir21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1124	鍐插嚮娉?	wxid_9hjfmrir6g5g12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1125	榄旂帇顒氶€犳櫙		sdd52119	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1126	Connor		wxid_ilka1bblk55312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1127	婀涜摑		wxid_89q6foegma1t12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1128	绾哥浜篐OW		q375496849	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1129	Y		wxid_ajtrs9rhl4o722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1130	J09		wxid_zi4f0fygyuxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1131	vx30		wxid_dmaffzcm55qp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1132	Beatrice		wxid_uxllklak8weg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1133	鏅傦紙鍔犳补鐗堬級		wxid_xf5m0drjiv8o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1134	鍛靛懙鍛靛懙		wxid_r0n4j7pb4lvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1135	閲庨┈		wxid_ldbd9r6j6pfm12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1136	璞嗙背		liulei708545	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1137	Mr.Nobody		wxid_4hrbmameastg21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1138	Mr.Black&)))绌烘皵濞冨▋		wxid_i1ce0oxuuxj011	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1139	椋炲熀		XTY158168	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1140	鏉?	pingshenme2011	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1141	鑹插奖鏃犲繉		yiyang0315	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1142	妤藉厛妫?	xiaoqiang627034104	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1143	鍙叉檽榫?	wxid_2g60g8mx7orv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1144	鐜嬬惁Kenny		wxid_w3rhn5orvbrc11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1145	鏈€浣虫煇鏌?	wxid_bab6ywd5fxco22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1146	鏉庣嫍铔?	makoto-and	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1147	鎰涘劒鍌?	wxid_fmph32vrb71t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1148	鏃犳仚銆侌煔€		wxid_9141671416313	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1149	銆婄劚銆嬬値鐏煍?	wss972522218	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1150	Jay		wxid_nxjgnsp9hhb941	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1151	浜?	wxid_6jqk87i3ml9u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1152	Levanter.		wxid_70enuov2vi2p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1153	楦ｅ		wxid_oqtaej5flvvc21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1154	闃块噾鏈夌背		wxid_q76n2hee5v6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1155	璋佸湪璇撮浮鐓插急鍛紵		wxid_ll2la2xq7a4u21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1156	鑹烘爲瀹?涓撴敞灏戝効鏁欒偛鍗佸勾		wxid_vt4gub7c29pg12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1157	greAporkwArd		jianglin2045	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1158	馃悜		wxid_98ffsxmgpz2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1159	鍫?	wxid_yj1vsehe5f6212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1160	A.寮犵敓		wxid_uwy1oa4zqjbm21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1161	cz		dean897436	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1162	涓嶈棣欒彍		wxid_zxkp19z20ifq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1163	Jon		wxid_en4eaxvl5p2232	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1164	璨撲汉		ahan1917	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1165	灏忕鎴佛煒?	wxid_n81j9cypp96622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1166	o_O		wxid_iydhcgs3jgjn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1167	Too_bad		gao455055157	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1168	鏂囧垁鏉?	wxid_xbx6zyb08yk621	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1169	BIG鍗?	wxid_49weqi0xj0g622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1170	鍒橀樋鐧?	liuabai	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1171	LanBing		wxid_5hthzdoi2k7c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1172	AAA鍑忚偉鑽壒鍙戝晢灏忓垬		wxid_leh7x2zhwstd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1173	AKUMA		wxid_gbhgsisn9ovm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1174	娑傞甫		wxid_dx3ktp50wc0n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1175	peanut		wxid_huu9312y0fyd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1176	浣滀釜閫傚悎鑷繁鐨勫ソ姊?	wxid_qv0dzkvt6li122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1177	鏉板凹		wxid_f8qw9ot63eqc12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1178	鐧界焊-榛戠嚎		wxid_g442karxvaan22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1179	鏍?	chris52794567	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1180	nuko		wxid_pn0ac34c5kdr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1181	Plan Z		wxid_9x58jttsz0mc12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1182	David Z 庐		wxid_mi8xpd8mmot311	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1183	Boa Esperan莽a		wxid_frlfu0h5dg7c12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1184	鏋勬柟		wxid_so2qyzasukdh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1185	鐤鹃		JF617202556	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1186	浣欐偢		wxid_28f93nn1mr4k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1187	濡傛灉鎴戣兘娲诲埌涓€涓囧瞾		wxid_d41iqcxtqa6j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1188	寮犵憺		wxid_n1chlr1pnp3o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1189	鍦ㄤ綘鐨勮韩杈?	sunxiaotian133983	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1190	鐐庢睈		wxid_aafr7379x37p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1191	鐔?	Backkomly	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1192	Rain		wxid_xpyq3x7v0c9k12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1193	鐑埍鍙姷宀佹湀婕暱		wxid_evnnr4c7skt022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1194	涔斾箶		wxid_q893jtijxoxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1195	Heathens		wxid_q0lh3vcjsmho22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1196	馃崼寮犲紶鍖?	wxid_aet4k5ad4bwv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1197	wxid_c87nj9dhn4h222		wxid_c87nj9dhn4h222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1198	闃挎眬		wxid_1642166422213	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1199	銋ゃ叅銋?	wxid_es9d03wjf2bd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1200	闃垮反闃垮反銆傘€?	wxid_p1aa9r2dw60q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1201	鍙吔		wxid_6d6o76ew2k5w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1202	Haru		wxid_kzxfbatrkvvz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1203	鑾厡		wxid_2mzbymkl33lc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1204	灏樺０		wxid_i2v1q41hbcm822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1205	閫氶€氶兘涓嶅湪涔庝簡		wxid_sg1gc14c2g6t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1206	^-^		wxid_u3mhp3qoqq0j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1207	馃崐		wxid_52ei3i24njfd21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1208	鎳掓噿鐨勪笐楸?	wxid_imbmwo0iu73521	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1209	KZY		wxid_vkzs9zsjunsk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1210	姊︽煋鑺卞		Arsenal199101	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1211	鍖楁礇BG8SJV 鈧呪個鈧?	wxid_8k5payct9vqp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1212	Une nymphe 茅l茅gante		wxid_ag2fr4khq6uq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1213	510188		wxid_sel9aknw69zd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1214	鐩?	wxid_w74vjlcdqb4h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1215	瓒呯骇灏忓		wxid_qzyqa4b5saso22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1216	A鏉ㄤ簡涓槼		wxid_pxidfjov4ju022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1217	鐖卞仛姊︾殑妗愬厛鐢?	jinxintong7699	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1218	鑳?	wxid_eobe0mvtnc9122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1219	3宀佸皬瀛╄娣辨儏		wxid_snqvtnem4jmv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1220	LamKimHing		wxid_tswmcqtwhpnu21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1221	+		free1995	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1222	Reverse Entropy		wxid_5765467654812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1223	灏辨槸锝?	wxid_n2f0a7skw8jx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1224	浜?	wxid_kos1o1sgh61g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1225	瀛熉峰搾灏斿搯		wxid_tzu3x8pyvtqp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1226	涓€鏉＄嵏		wxid_u12j3uoay56p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1227	娑涘０		andongni_1468	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1228	娌夋綔鐨勫皬楸?	wxid_f8u8ev0aowr822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1229	Serein		wxid_nrskwseq4ug922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1230	瀹?	wxid_vz7mom8s6mib22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1231	椤句繚淇?	wxid_02fvyygilcft12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1232	姊撳仴		wxid_c0i31erxwhsb31	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1233	绋?	hcjj88	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1234	瓒呯骇鏃犳晫鐐叿瑁呯敳闇哥帇榫?	wxid_85nlvkf0v7wv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1235	Ezio		wxid_zkk10u6riyb522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1236	鍝堝搱瑁?	wxid_ddr0qq7u5lgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1237	C		wxid_qsp94qvby9h222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1238	鎴?	wxid_uwldae25mg7522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1239	forever		wxid_18d0bw96ke0t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1240	Leo		zxhaha9527	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1241	鏉ㄨ懕澶?	xingzishuai	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1242	Richard		wxid_j9g7hyrk9q5t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1243	灏煎彜鎷?鐗规柉鎷?	wxid_5qmd9j5tfafk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1244	A锛?	wxid_non12chx1vtd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1245	銋?	wxid_4krse5zla09h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1246	ABCD.锛堬級		wxid_iscihvmmu2xb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1247	璞嗚厫		wxid_mbbue9w2ja4r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1248	Jillvalentine		wxid_80bz67rar1au22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1249	RHT		wxid_lxxd330e1tqp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1250	ou		wxid_ao8gks2tebwl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1251	wsm		wenshimin1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1252	鑳栧槦鍢熻偉瀹?	wxid_rkoig00uafrv41	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1253	馃惗 娉?	wxid_p73mykh5c1hc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1254	銈娿倗銇?	wxid_uca2rxfry97f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1255	Linnuo鏋楄		wxid_5djnas27oddv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1256	鏂板痉閲屾竻鐖界殑鏋告潪		wxid_qb02bho5seg612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1257	MT		wxid_2pe7i93uoph511	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1258	鏈堥粦涓嶅牚琛?	wxid_gzr5hd1vs2nb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1259	trophies		wxid_wqmeuh8erzeg12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1260	Formula		kimi380441406	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1261	鎴戞兂鍘荤爜澶存暣鐐硅柉鏉?	wxid_5muomrg2a2h522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1262	浼氱寽鎷崇殑灏忓彯褰?	wxid_ialm02i32l3u21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1263	榛?	wxid_wevyhalwvpli22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1264	闂€€		wxid_dpo5psh2fvdo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1265	鏍?	hami25	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1266	馃挦 YOGA馃懟		QQQQQQG	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1267	鍒樼儊		wxid_13xkoza7eb3521	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1268	闆惰惤		wxid_3mhrhuejyht022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1269	搴勬檽		wxid_cuzpn16etzy022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1270	AAA闃栧骞哥		wxid_ohdrc06v20tx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1271	nina		wxid_pu2jqtm4hn6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1272	涓€涓偣		wxid_gmhpjswdhn3122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1273	doki		wxid_2k7gx3w4qo9a12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1274	鏉ㄥ喖		wxid_p547do3ue6o712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1275	椋庡０濂藉惉鍚?	wxid_4xjh6bv4t6sl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1276	鐏粷浜烘€х殑甯堝叕		wxid_1qdanfdycb5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1277	luvu2		wxid_1nx5ju273t0g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1278	Laikaz		wxid_n5mas3mniks422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1279	鑲?	wxid_64q79l9symgj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1280	钃濈槮涓嶉鑿?	wxid_gqhk5nkm7wsk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1281	宸ヨ棨鏂颁竴		wxid_7vo7nr0zn1ms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1282	妗冭姳鍟婃鑺?	wxid_fglvzo3x3d6j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1283	鎳?		wxid_nvv0ds3382e722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1284	澶忓ぉ		wxid_8yqmjrs3fc4421	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1285	閭伓鍚夊▋濞?	wxid_ldlx44rxo60a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1286	鎬?	wxid_ci8aithyn1cs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1287	鏅厓		wxid_9jpm8ooohj6w11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1288	馃崐		wxid_5pncl6h29zqv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1289	涓€韬嚊鍐?	wxid_0mfkrampd1rz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1290	鐨囧緦澶ч亾		wxid_agpwp6mzv6di21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1291	A灏忓厑		liyong2692	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1292	鏉庤垳鐢?	wxid_t5zwkov36juj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1293	娈哄崌灞夸父'		wxid_t7a3lervw01q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1294	鑴辫剛鐗涢┈		dwh821528394	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1295	浜戣緣		wxid_zf0wphrkh53v21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1296	Rukawa		wxid_bcyj1htsp63o12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1297	甯稿彾闈?	wxid_gzdgozbt93e712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1298	浜屼簡涓簩		wxid_untklm0ucsg522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1299	鍩烘媺澶ф牳妗?	wxid_yhm5qi3f89ih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1300	绾埍鎴樺＋鎵嬫挄鐗涘ご浜?	wxid_k6yoic8ue3a722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1301	ym		wxid_ubgx2ggum33y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1302	Sizuku.		wxid_h1zu2oqfurxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1303	閱掍笁鏃紝姊﹀钩鐢?	wxid_wbiwh11cochv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1304	WO鍡崇綈闋?	tianlehao	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1305	777		wxid_ah1lg8zc4nsb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1306	1		wxid_fo1q98n33xs122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1307	Ikarus Timothy Type 伪		wxid_k8x7k4yog4i812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1308	Norson		wxid_xmte1lc9shx122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1309	灞呮槗		wxid_h7kkv3uvv8zt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1310	浠婃棩鐨勯鍎跨敋鏄枾鍤?	wxid_xem086cibh6j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1311	瀹滐紙寤烘ā锛?	li840514	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1312	娴佽嫃		wxid_rlgq07nqoxs121	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1313	鍞愰涪		wxid_tgq1u2umg5qp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1314	閲戣眴		wxid_paek491warv222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1315	濡傛爲		wxid_aqcjzga3un9722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1316	chunyiran		wxid_qzn1pzk4zt1w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1317	TK		wxid_82ui3pjul9an12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1318	铦?	wxid_qkprd4xka1x822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1319	姣忎竴鍒婚兘鍍忔案杩?	wxid_b16loathwjd822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1320	鐨?	wxid_7jpdtu72fo5w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1321	璺汉涓欚煂?	wxid_w27bh20t5jwy21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1322	cos虏伪		wxid_q2e5wlolo43822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1323	wuuu		wxid_nmrzipvtn2qw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1324	浜戜腑姊﹂啋		wxid_13x8lsrlvv2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1325	璋滆浜?	wxid_glb767x5k6ok22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1326	鑰佽タ鍖?	wxid_tndbtmj1hk5a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1327	榛戦緳		wxid_tsojbw70z3zd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1328	鑲栧奖闅忚		wxid_35f7pifv4swo21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1329	Mr.Samoyed		wxid_0146361463912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1330	杩滄柟		wxid_nmsl1gqojitq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1331	鏋?	wxid_7tcs7o8gimkw11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1332	鑸嶇敨鐞寸		qq235815102	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1333	鍏讳竴鍙尗		wxid_b9nennldtzf621	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1334	k		wxid_17qevxqrxwdu12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1335	yi		wxid_stnbp543qd3l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1336	螕		wxid_1njr5k7xs73o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1337	瑗跨孩鏌?	wxid_4dfu8xy7e1no22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1338	馃		wxid_z30qoucbhgcv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1339	澹规澹?	ou154586079	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1340	闃撮鐙傚惞锛屾垜闂负浠€涔堟病鏈夌窘缁掕￥		wxid_r0gjkts92r7522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1341	褰?锟锟ｏ紱)褰￠涓噷涔?	wxid_os7jkfrobgdr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1342	6		wxid_vyrvdpogrdx112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1343	涓€鐮氬揩闆?	wxid_3528725288612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1344	dangerous		dangerous832336	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1345	ReikoLiliy-official		wxid_478enj9h1iz322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1346	馃		wxid_d4azkkejebwy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1347	.		sun19920713	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1348	涓€姣涘叓 馃寶		wxid_71x3c0cj2erc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1349	L . D . Y馃馃徑		ldc670992546	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1350	Forever.灏忛粦		wxid_u81b81vdsarc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1351	澶у墠閿?	china9815	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1352	榛勯摦		wxid_fm9pao3f04ri22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1353	馃捀		wxid_l3embkkgz1s122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1354	鏈堜笅姝?	wxid_7440454404012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1355	鑱嗙晫		liugeng360	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1356	涔愰		wxid_ymnspzsp1tjx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1357	keep		wxid_1zdhgs0y8x7s22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1358	鏉ユ棩鏂归暱		wxid_jf21t6wlqchs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1359	鍛ㄥ崍		wxid_l373jnopanvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1360	D4C		wxid_g1f603vzlvbj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1361	绉嬫按		wxid_9unzhlvooqtn32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1362	BOSS		daizuo003	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1363	馃悳		wxid_4etyiaznhti121	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1364	浣犲共鍢?	wxid_uiog41m9odee12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1365	AWA		wxid_i46g230zy35322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1366	l-l		wxid_j5qr5xtht5jn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1367	鏍?	wxid_qmomtputzk4a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1368	馃嚛 馃嚧 馃嚦 馃嚱		xudongdong1115	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1369	鍛嗘瘺		wxid_gspcvv7cbpne21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1370	馃惌		wxid_m7xqmq9om8k321	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1371	.		wxid_8asm56a9sllf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1372	馃嚚 馃嚚 馃嚚 馃嚨		wxid_btphe01huco712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1373	娴繀鎽т箣		wxid_2w8cjvtp5t8412	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1374	Red eyes		wxid_frufiaqwh6i112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1375	鏃ヤ赴鏈嶅姟宸ョ▼甯?鐜嬮挵		wxid_oyf9arlvm21g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1376	9戮		wxid_2imeb3l8evho22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1377	璧烽浜哵O^		wxid_tohixb597uj022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1378	鍒€閰?	wxid_6nqo3k3i2bnu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1379	娌愭辰锛堝井淇￠潤闊虫湁浜嬫墦鐢佃瘽锛?	lixiaonan0813	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1380	闈掑嵂瀹?	wxid_mz9nq3pl9b2p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1381	Jinx		wxid_emyu8x9akwjq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1382	just her		wxid_f3v4fgzvtxmv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1383	闄堥挶		wxid_tkwgy3aqsa0k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1384	鍙屽眰鍚夊＋姹夊牎		wxid_wlgj5vtik4eh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1385	AA甯岀鑹烘湳(寰楁湀鏍″尯)~寮犺€佸笀		wxid_yyvdog92i73e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1386	琛ｇ唬鍗佷簩绔犺姳绾?	wxid_v34l7k7h2w9q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1387	闀垮矝鍐拌尪		wxid_o8g7y5vc7ssr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1388	鍖栭泤鎬?	wxid_65drna74owwy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1389	鐧界櫨鐧?	wxid_uh1fsdkxoyjt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1390	澶滅櫧澶╁痉		wxid_v6cfelf8fbpq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1391	鏈ㄥご灏忔瀛?	wxid_e4adynzm6f0022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1392	蟺		johnsonjd	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1393	X.c		acexing7	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1394	瓒呯骇璐濆悏濉?	wxid_uhdrbxpdv9dv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1395	YI		yige_baby	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1396	姘存竻姊﹁摑		wxid_s1f7vqv3nheh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1397	钃濊帗		wxid_125rei6mubxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1398	Leeshu		TREE800688	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1399	鐘硅鲍鐔?	chenleiming876858	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1400	馃崉		caiyaomin002	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1401	鎴?	wxid_166p447l8ik322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1402	绫嶇繉妗?	hobabby	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1403	灏忛檲		wxid_0epk9se3bw4k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1404	鐜嬪畨娉?	wxid_rkhoowvsay8k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1405	绉?	wxid_c5ellm9ng79751	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1406	鐚?	maozai9199	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1407	椹偊		wxid_qh6gj4t8gl4x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1408	^O^		wxid_f1pt9017gim822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1409	鏌扴even涓?	woaisiwy	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1410	up馃嚚馃嚦 sunflower		wxid_flfr0afqy90q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1411	idom-pow		wxid_127okc0opkpt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1412	Lc		wxid_hklkig6n913l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1413	Homer		wxid_7357363573912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1414	hhhhh		wxid_8guvysxrmfvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1415	鍒樿幉铔嬮粍閰?	wxid_3391653916512	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1416	Shelter.		wxid_vwispnw6qvpg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1417	浜胯垷鐗╂祦		wxid_cwqcrj6m7aso22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1418	鐫′笉鐫€鏁扮緤		wxid_jxjge5ztvt4d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1419	LUMO		wxid_96iwypj6loox22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1420	鐭ヨ冻甯镐箰		wxid_rlfu404p390d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1421	馃崯		wxid_t76fora9kdfg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1422	浠€涔堜粈涔堜粈涔堬紵		wxid_49hj299e8q9722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1423	Calyrex		wxid_ilzezv0ysimi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1424	鏈€侀附瀛?	wxid_8k47s033rxj022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1425	Vacuum		wxid_ai09u3cwdwtx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1426	rewrite.		wxid_dvvkx2ie968b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1427	鑳滄棩瀵昏姵		wxid_rzdvt7aqbh0d12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1428	鏅撻箯		xiaopeng452439	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1429	Leo		quanxiangjun002	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1430	:锛?	wxid_kolgriiszdpj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1431	灏忎節		wxid_lmxvjcmr3qmy21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1432	馃崯		wxid_xag8mu1xdegz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1433	姊︽绱～		wxid_6z35tyfzj24y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1434	鏋椾害濞?	wxid_877igsfkin8119	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1435	Emagon Efilon		liushuihanshu	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1436	Tempted		wxid_8b9qpkzcf6v922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1437	鐮磋導鎴愯澏		duxuanji	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1438	Emerson.		wxid_dmvlqj1r0kml22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1439	鎹烽澶х帇		wxid_pyx1sqk8owq829	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1440	绱犻闀挎湡		wxid_iu863uleoehv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1441	馃拵		wxid_5qmh56ij0pea22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1442	Jeremy Kang		wxid_kvpmfylv6fo421	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1443	Sy		QQ100530860	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1444	澶跺績		wxid_cctrww0s718522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1445	鎴戞兂鍚冪伀閿?	wxid_x2lbqigr9nwl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1446	鏅?	wxid_l4m9kbgh36r822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1447	馃寔		wxid_djzmbeacbfqf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1448	ZR		wxid_zae89tl1e8un22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1449	.		wxid_68xzk993iecl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1450	鑳栧瓙		wxid_jovktpwuh51w21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1451	Golden Boy		wxid_yurppmm0hhlj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1452	Mr.Li		wxid_7f04aqe6if1w11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1453	褰╄櫣馃寛		x8888k	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1454	涓夊崈闈欐按		wxid_mpwi03mmixo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1455	灏忔柟		abcd7765195	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1456	MG		wxid_k8sdx59g605h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1457	澶忔湯		wxid_94yjiu28nibm21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1458	J		jie494402524	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1459			zyc199712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1460	浠ヨ吂涔嬪悕		lx48034604	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1461	鍗庡叴涔︽硶_鐜嬫浜?	qq243096205	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1462	瀛欐偀绌虹殑鍏冩皵寮?	wxid_ovqkyiueafut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1463	閬ユ帶鍨冨溇妗?	wxid_zpdnddn8slek22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1464	鑲ュ槦鍢熷乏鍗棬		wxid_nvivbb6kihvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1465	鏉ㄦ櫙鐒?	wxid_bsti3t6uo4bd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1466	椴瞜		wqk1181781267	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1467	TOMMY顒?	wxid_dlmei5ab3o2f22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1468	OA  OA		wxid_feqy4xi48ef312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1469	灏忕伩		wxid_5fjnz0w5c13v21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1470	鍌呭懆鑰€		fuzhouyao	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1471	muffin		wxid_svebfllr3d0n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1472	闃垮反闃垮反		wxid_dsf9ihwf0bq622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1473	Kiko		ztt3121782	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1474	Links		wxid_340lukenluqm21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1475	Do		wxid_92neuvn75zjk21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1476	715		wxid_8ax2nhpjp0au22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1477	褰?	wxid_2oal2gpsgn0d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1478	灏忔灄		wxid_g07l5q9m4hd412	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1479	鍙や粖涓绗竴鍞愪汉		wxid_fx25otur82cf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1480	Gikr		wxid_kyp13ih53im222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1481	榛勫姞钖?	sea_779705046	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1482	JingpengLee		jinyu_0505	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1483	浣虫垚		wxid_sj0ka7e9lc0q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1484	璀﹀療鎶撹醇涓?	wxid_l1b7bhcxsmri22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1485	瀛?	wxid_zpuv3miwizy622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1486	鍍忔捣涓€鏍?	wxid_qrj0a2hj7ohf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1487	澶у北		wxid_6ih6cgytsy1w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1488	鏉戦暱		wxid_3wp4q4777de422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1489	灏氱ゥ鏉?	wxid_w4nyng48q9ju22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1490	To treasure銆?	caocao1224	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1491	Gekilt.		wxid_ma4lo578k9nm	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1492	door		wxid_elt17emypehf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1493	绫冲叞鐨勫皬鐗欏尃		wxid_lqfvd3zg5xag22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1494	娓呴		wxid_m0vq82ib3pu622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1495	鐧芥按鐓櫧鑿?	wxid_ec3heh0gye5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1496	kk鎶?	quchangkang	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1497	caviar		wxid_j7pqz4cp2ovs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1498	寮曟浮寰樺緤		wxid_yogwtdzeh4h212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1499	寮犱附涓?	wxid_7464734646912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1500	馃尵楹︾		wxid_a160x1l70w4722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1501	浣╅渼		wxid_h1aplf3rd8ut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1502	fish		wxid_q6tw1lkibvs422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1503	Jesse		tanguangduo	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1504	鍝堝柦		wxid_507ujfkbxecs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1505	闀挎矙鍒洪潚.钘ら拠		wxid_c0csfu4rwl4a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1506	璺戣皟鐨刌s		wxid_1x5xt3gi3rs121	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1507	 閾舵爲		wxid_aa178c9lqr6z22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1508	鐨煇旂帇		wxid_vq6gtuga3npt12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1509			wxid_7kt8ciou07oh21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1510	銆?	wxid_bcfwuamd5hhv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1511	娓呭槈銆?	wxid_od3yin8rjaxo21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1512	鍦扮悆澶憶浜?	lm9371	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1513	闅忓績		wxid_iy660e38v2ok22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1514	SuperMariO		k531193626	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1515	璧礩h.		wxid_pipjcof1jg2f12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1516	锛熴€俴		wxid_ms8b4fe6d4fg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1517	馃殌 馃寱		wxid_jo75l2iqsjn122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1518	C.C		wxid_qm0k4ofyoqoa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1519	娴敓		wxid_ljdwzgm73uzt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1520	%		wxid_onlo047g6rp622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1521	銘?	wxid_cm5jff460mvj12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1522	涓€鏋?	wxid_329g71qu9vzz12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1523	chercheur鈩煍?	L357535	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1524	鐑熺啅闆硶		wxid_zmbd6olaw6ax12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1525	WA銉?	wxid_mrllb1cfx1lj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1526	锛?	wxid_witw7gctj9sr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1527	馃悕姣旂壒馃悕		byteuser	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1528	浜洪棿鐑熺伀		wxid_9ztrnpf1bmod12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1529	楗煎共		wxid_ff84y99rxyeg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1530	鍐板喎		wxid_tofm556vkot722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1531	鐖卞績鍖椾含		wxid_j4tfk24njup951	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1532	.		wxid_leu2ea4uy8h522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1533	鍚?	wxid_njyd4346vpvm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1534	馃崁		wxid_xnt05oqoab1g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1535	鐖辩潯瑙夌殑灏忓紶		wxid_5h3avpbhp6gm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1536	灏廏en		wxid_9y9ncenspwgi12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1537	鏄ユ棩璐熸殑		wxid_ylg3579r2fqf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1538	Sn		wxid_5ex9fj3mfoxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1539	鍒濊		wxid_emx4nv0xy8tx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1540	鐩肩悏鐠?	wxid_7oyuvaorapci22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1541	璁ㄥ帉涓嬮洦澶?		wxid_4y6c7jbd67uq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1542	銋?	wxid_6jm7wim5xw9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1543	瀛や簯		wxid_h0hhynnp1lut22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1544	娌堣瘝缃戠粶		wxid_79a5ouzr2mdr12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1545	鎯呯华		wxid_1ex647zmihdy12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1546	Wang.		wxid_sln3uqhho1h222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1547	澶辩害		wxid_wu12qsouvp8422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1548	cikzlp		wxid_40pcubjhryr522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1549	鎬濆康		wxid_yp02yxyug2rc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1550	娉棧		wxid_nzj2fvpi2sx122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1551	lock+		wxid_iuj05q4of8lg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1552	澶忕洰		wxid_typ3q01btqr522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1553	瀛ょ嫭鐨勭嫾		wxid_8b2rlguhp8pt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1554	ZY		wxid_11jahlk3cfz622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1555	鎯熶竴		wxid_cclxjdrajqbf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1556	鍒濋亣		wxid_6wmzmpgfnpr529	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1557	鐧芥儏PP 鍓彿鍦ㄧ嚎鎺ュ崟		wxid_oertcgjbbgkq12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1558	24ttyd		wxid_6nzwmccqxk6m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1559	娌?	wxid_arb5ie58d20022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1560	.		wxid_bhca5mwdmlih22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1561	婕崱鎵?	wxid_2tzthk7t6r7522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1562	鎴樻崯鐗?	wxid_s01s92424mli22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1563	C		wxid_63zobm68xvhf12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1564	璧靛皬涔?	zhaolele1409	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1565	浠庝笉杞绘诞		wxid_s3he23n3z3pq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1566	銆?	wxid_1ngqz5tnsseu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1567	w		wxid_d3an8c90x90x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1568	绋嶇瓑浼?	wxid_brodhk730psu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1569	鍝堝搱		wxid_wl550z0x5eth22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1570	闀块		wxid_gwbf7bwkdt4n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1571	Zhaoyy		wxid_mpc3wuclmmdh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1572	涓害馃憫		wxid_bqogvy1vipo321	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1573	鎱?	wxid_lougwyukckth22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1574	闆?	wxid_68h0lcigytfq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1575	Useless		wxid_8gndfk3n288522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1576	涓嶅啀骞磋交		wxid_eof7wqesnbka22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1577	L		ai1402665050	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1578	鬆€€		wxid_x5z2b4st3hlc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1579	鐒剁劧		wxid_zd9deolq273l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1580	绉熷ソ鎴裤€愪复娌傜鎴裤€?	wxid_edxtwbemwsqm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1581	Restraint.		wxid_thtdzqs2ij8y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1582	閱掍簡		wxid_ijk3jtldg2qp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1583	娴粩		wxid_n5yzkr2udh3r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1584	琛岃€呮棤鐤?	wxid_o6lygemrmuz621	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1585	鑽旀灊馃崚锛堟湁鎯呮湁瓒ｏ級		wxid_3rtt869ow2kd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1586	鎶樿€虫牴鍑夋媽鑿?	wxid_v6d6mbmymnqz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1587	-A鏋ф磱PUR-瀛欓		wxid_7xhz6t0y7nox22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1588	馃挙		wxid_wtsrr91imyk922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1589	鏅ぉ		wxid_96jxekqdipuj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1590	A骞冲钩瀹夊畨		wxid_hnpll8ihxpsr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1591	涓€璺敓鑺憋紙99锛?	wxid_naro8j7x64lp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1592	蟺		wxid_1b1ipm22yasb12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1593	銋ゃ叅銋ゃ叅銋ゃ叅銋ゃ叅		wxid_m2mvn3ouhv8k21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1594	姊﹀紑濮嬬殑鍦版柟馃寠		wxid_8sa8no2fwe4h12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1595	浼?	wxid_9nwhg78zdp1j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1596	閭ｄ釜鐢蜂汉		wxid_5mq4x5rnlpyk12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1597	鍜屾皵鐢熻储馃嚚馃嚦馃嚚馃嚦		wxid_p5u83i5iuu9q11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1598	姗欏寘		wxid_1xdue88fdxwi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1599	Y		wxid_es9zxvrxr7d422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1600	銆?	wxid_f2zwphlth3xv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1601	寮犲杈?	wxid_206z6yc9u9k612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1602	濠峰┓		wxid_0utg3o46qj2p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1603	銆?	wxid_28df8ox4acm522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1604	鎳掑ぇ鐜?	wxid_wanelf2ds5rv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1605	鏄ョ铦?	wxid_pk6ju53e2vjd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1606	YaoIo		wxid_0z0zokm500ws12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1607	娉棔虏锛堟帴浠ｆ寕 鏀舵€ュ嚭		wxid_0i4xuwxnjug212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1608	L		wxid_769g7t2tfxn722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1609	deft..缇婇┘		wxid_czh6toxo31h922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1610	闃块箯		wxid_7j3qv36smutq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1611	锛?绾紙杞诲ア鐢靛晢锛夛綔绉佷汉鍙?	wxid_oeorsx7p14ud22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1612	Ch.J		chenjia008011	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1613	姝ｅ湪杈撳叆涓?..		wxid_gjfhunt782zt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1614	k		wxid_kfj38ao8ettq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1615	.		wxid_9jmiihf8rgdh12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1616	pretend		wxid_dw89kxe6c24u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1617	馃		wxid_pslevqj94vwb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1618	绱彍铔嬭姳姹?	wxid_69dfknjd5hy722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1619	涓?	wxid_ub19js725fy022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1620	銆?	wxid_fz698edkxzn422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1621	灏忎嚎		wxid_zdnmwoi9jepj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1622	鐣?	wxid_jm1omo9c4ssr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1623	鎭?	wxid_h21sobgg2enu21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1624	骞垮窞鎺ュ彂鏌撳彂澶忚馃Ц		wxid_fimwfucj6ta322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1625	A鏂囧北鍐滄湇		wxid_32e1yfl7lrkw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1626	~		wxid_jbwa663dysx122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1627	Crypto.0824		wxid_5ltpg6mhx4ft22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1628	鍗婂		wxid_8g1hf9w1zita12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1629	钃濇		wxid_jr99cnx7yj0q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1630	鍗佷笁		wxid_zci4ncuvbdvs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1631	wxid_h76y7jdelptq22		wxid_h76y7jdelptq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1632	鍢诲樆涓嶅樆鍢火煠?	wxid_cmfz6qi9u27522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1633	Continue		wxid_cttz1al5gsx422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1634	澹?	wxid_fme9ugo0p8rv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1635	浣曢亣銆?	wxid_urvigcg8ainu12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1636	鏈堝嵖鍐?	wxid_c23623hxrggc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1637	灏忓畨		wxid_vdsqfg8n87di12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1638	A渚涘簲閾鹃亰鏍瑰伐鍘傘€愭湁浜嬬數璇濄€?	wxid_x93h1byurb5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1639	17		wxid_uagah9afgqvc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1640	淇紭		wxid_5dnxuthgm0ws22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1641	閰?	wxid_1950udkzmpqm29	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1642	馃エ		wxid_1uxiadfso4qj12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1643	鐖变綘		wxid_3874098740712	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1644	浜嬩笌鎰胯繚		wxid_6z4e5k51a56w12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1645	鏋工		wxid_nxrdlknivjq929	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1646	妫掓鍫傪煃?	wxid_0ssx4482ct9n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1647	uk		wxid_4qpytpwqp4pg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1648	Y		wxid_pbgyiw4fwryd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1649	瀹囧畽瓒呯骇鏃犳晫闇归洺鏆寸嫍鎴樺＋		wxid_q8uk9kli10hz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1650	绋嬫枃鐒?	wxid_ybmfejtp2f9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1651	绉嬮缚鎶樺崟		wxid_6glyc962ww5j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1652	榄傚綊		wxid_doj7udfrzxj322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1653	瀹ｄ紶灏忕粍-淇嬀澶х帇		25984984402748767@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1654	Alex		wxid_h6xrmo3qqqgz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1655	岽贯祪矢		wxid_iopqwrsnjxbs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1656	QX		wxid_v2c24kgjbj8e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1657	绂剧		wxid_v6sb4ihhaw8422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1658	瀹ｄ紶灏忕粍-榄傚綊		25984983370117784@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1659	娲?	wxid_kzxt4tmco14u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1660	鍚垜璇翠綘鍏堝埆鎬?	wxid_jnvgzz3h400d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1661	Anan		wxid_rs8lpz59mggm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1662	灏忛儹鍢?	wxid_x27u05mta4h922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1663	闃縌闃縌		wxid_krcrzg55rzho22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1664	鏄熼槞绗?	wxid_oekezzsbl2xv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1665	绉嬫按		wxid_albywejs52t122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1666	~寰€浜嬮殢椋巭		wxid_j72e5vj1zmdh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1667	绌虹櫧鍚?	wxid_lly7aul55h5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1668	婧愬皬鏍?	wxid_oxibqjkaphd122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1669	鏃犻鎴戦粛		wxid_e9l728s5l5kn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1670	灏忕尗鍚戞棩钁?	wxid_5xyyvc2y4ore22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1671	:		wxid_mytfrbpr6cj722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1672	嗉?	wxid_93e143i170u722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1673	鏉忓康寤夸笁		wxid_9sjomwkn7o0t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1674	骞插噣		wxid_g6vzy83t9sxr21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1675	娌堟柟骞?	wxid_36i4ez83lt9x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1676	鑿犺彍		wxid_3provepfz3b622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1677	楹荤椆鐨勫皬鏃ュ瓙		wxid_zv9edwsfjnkj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1678	鏇归晻		wxid_m8uzrlk1umrb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1679	Tim liu		wxid_d961vtzlg1wv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1680	shjandhaj		wxid_xtn5luat4zx422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1681	鍑濇湜		wxid_gr2ictbdtd3o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1682	Komorebi		wxid_y36z1zq48kf322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1683	wzc		wxid_npelebxuzm2522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1684	鎽嗭綖		wxid_a3sa1ujqikrs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1685	鍐竻瀵?	wxid_aqvq76nm9f9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1686	骞?	wxid_hwmgvub6dlvf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1687	WeMaX		wxid_jma064hshi9h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1688	澶╂灑		wxid_ev2yizwzn2lm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1689	鎯熸効鍊氶潚琛?	wxid_pj7kbyubkmzd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1690	鏄熷厜		wxid_r48btk5szrp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1691	Kar1m馃導		wxid_up1i3uazmatn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1692	鏇﹂		wxid_lpml0ziw728l12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1693	绻佹槦钀芥ⅵ		wxid_aa4eh1ylgaqc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1694	鏌氭熆妞拌帗鏌?	wxid_rnnjlcvom1zd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1695	喔?	wxid_xmge1c7fqy422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1696	璋㈢灮		wxid_3040600406322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1697	榛勫畤鐣?	wxid_w3pa1gpkgi6222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1698	銆傘€?	wxid_2k9olcspqi1g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1699	10		wxid_bl1mogcyeumy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1700	ssa		wxid_aftyevpfmjlf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1701	lightlightw		wxid_w7fzleevyn6c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1702	Joker Zhu 涓?	wxid_82tsx7622yt012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1703	鍚存槑涓?	Eee478303	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1704	鑺卞紑瀵岃吹		wxid_qi0rs2jalglc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1705	锝烇綖		wxid_ggjt3lwpdncs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1706	鍚		wxid_awrwd73g4s9u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1707	闄堟簮		wxid_p3tzg5pkdhfd12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1708	K.		wxid_5sh9p9ljlqx122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1709	閰掍笁涓?	wxid_lvg3f4t383mp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1710	绱彍绯?	wxid_kf0xyxhk2ooa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1711	鍋氳处ing锝?	wxid_y59zbqsltnod22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1712	瀹堟姢浣犵殑鍩?	wxid_p3wrrkfown3r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1713	馃崿钀?	wxid_vw7fxxxum9a022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1714	缇婄		wxid_lik0mt9f5stn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1715	鏄熴伄銈堛亞銇?	wxid_5672anoj7pf622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1716	娓呴厭		wxid_9rqzoxn7sif622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1717	J.Q.K.		wxid_6px6m6d0196p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1718	zxc		wxid_8i4ua2m2d7io22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1719	锛?	wxid_rj2bovp3x61t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1720	涓€甯嗛椤?	wxid_di9ku6wayj5d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1721	闆箣		wxid_qjg40d38ai0a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1722	Zin92.		wxid_qocjpcpisaqc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1723	hsh		wxid_ciibj3t3voen12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1724	灞堟尟闃陈孤猜?	wxid_p27clxi3ecd122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1725	绻佽姳鏃犳剰涓?	wxid_u51wrvljk5n812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1726	鑳℃亽		wxid_vqx0lgf46s0j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1727	04鏈€蹇殑鍒?		wxid_q13py2wxdbtx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1728	鐐樺崌		wxid_ocs3dcijtqbf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1729	閲戦偟閿?	wxid_fvx1wi3241ug22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1730	銈炪偒銉笺儔		wxid_90hbtq6g7o6p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1731	oh		wxid_ee8ad2sskue722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1732	Gr1m		wxid_u7x3iysxquml22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1733	鍒椂绉?	wxid_aunsbwes8w8122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1734	涓斿惉椋庡悷		wxid_1nzr3l54wscv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1735	灏煶娑岀拑		wxid_ayzhcdrv30ka22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1736	淇℃伅鑼ф埧閲岀殑闆跺彿		wxid_5rbt3x6uoaqt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1737	鍋囩孩涓?	wxid_n8t4bal6pce422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1738	鍏堢敓		wxid_o8osfnplxq4n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1739	浠诲皹		wxid_cl4690u4bf7v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1740	sunburst.		wxid_o06mbjjj949x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1741	Archer		wxid_e0udxurwazo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1742	銋?	wxid_w7rbbis0s8pa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1743	妗╁乏鍙?	wxid_yjfzongrx1zn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1744	浣曞埄		wxid_y71h5xaaea4422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1745	涓€绾告姌楦?	wxid_6aed846j6cnu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1746	鍦ㄩ噹		wxid_nv74q5otpo522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1747	绱柉妗傝姳楂?	wxid_64gmgiqoysuz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1748	灏忛珮鏄ぉ鎵?	wxid_oezqs5ni5hdv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1749	銆?	wxid_hag722drbn3u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1750	Xxx		wxid_zymxhidif36322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1751	榫?	wxid_bmxh2mgli7kx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1752	鐙勪匠鍚?	wxid_h7yctdr84jkw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1753	涓嶇煡姹熸湀		wxid_dazpyomfabe122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1754	澶滆景鐜?	wxid_e66v5s5hhcj722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1755	Road Width		wxid_qlecmrsbrz3722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1756	鑰佺埞楹昏姳琛?	wxid_uwkwqwr43mjk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1757	鏃犳晫閲庣墰澶х帇66666666666666666666		wxid_xb593fw83zwv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1758	浣欏績涔?	wxid_knar18koad9422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1759	娣?	wxid_u3kv56id7ndb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1760	EM鐖遍┈浠?	wxid_vhjm124h4kcy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1761	楂樺潥鏋?	wxid_u21fohc2h8g322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1762	宸偣甯呰繃褰簬鏅?	wxid_5cxuaz0gqt8422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1763	鎭哄.鏉滃叞鐗?	wxid_d1k1yrsl6iq622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1764	缃戝弸		wxid_03o4kib6lkoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1765	鐪嬬湅鍜?	wxid_kgk4mto2snkw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1766	鐖辩瀸鐫?	wxid_eifzs5m848ye22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1767	姹熻埜		wxid_e8a5hmi63ug522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1768	鍛€锛佸湡璞?	wxid_56kybqcmqese22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1769	鍛靛懙鍛?	wxid_3flwoh40fikg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1770	Receive.		wxid_rxatpzhboxcb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1771	鎮?	wxid_s0a9e839uj7522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1772	闀跨櫧灞辩帀鏍?	wxid_m49ufvuyufsh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1773	2鏈?0鏃?	wxid_ubplgzle5mde22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1774	绗戣█涓嶈█绗?	wxid_mhf4jpmvv35k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1775	ruler锛堟棤浜嬪嬁鎵帮級		wxid_6fo60nxqbtwb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1776	姝﹂攼鏉?	wxid_en188ylfu3k022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1777	yzc		wxid_738z32496lp622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1778	鍠濆挅鍟′細涓婄樉		wxid_4ieaol8mxsek22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1779	鍌茬		wxid_5k5853b36hu622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1780	C		wxid_bgwan0fulkd122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1781	闀挎€濆噳鏈?	wxid_5ibuvsm5fnta22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1782	璐捐敺鎬庝箞灏辨槸鍋囧浜?		wxid_ywxpwz859d9x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1783	-.-		wxid_uzosa0wjxn3o21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1784	鐪€鑸?	wxid_o0zjmamca6pj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1785	杈?	wxid_vdf30pvw5eqw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1786	钖潯楠戝＋		wxid_7glx3xw2ucri22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1787	闊﹂檧		wxid_3n6s2hyxkjsb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1788	路		wxid_i6afyymvzxgi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1789	甯屾湜鐞嗘兂鐢熸椿		wxid_747n3ekqzuxe22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1790	CHANGHAO		wxid_swnkth502hth22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1791	k		wxid_bbcvra32q3yk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1792	K		wxid_kjqsjx3235xe22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1793	R._		wxid_awzkcyl3tqtx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1794	瀹嬪 銆愬浗瀹剁悊璐㈣鍒掑笀銆?	wxid_oaw04kevogq222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1795	娈?	wxid_3sfojme37l3l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1796	绛濈瓭绾搁涪		wxid_03mv4jfx4ie032	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1797	Betsy.		wxid_i1ncx227dfwy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1798	涓囧嘲楹?	wxid_crdlrbx83cpd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1799	鍛嗗憜銇?	wxid_lq9lf381wy3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1800	selder		wxid_ekygpf9fyi9h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1801	BH6RZU		wxid_p31rok46m7q222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1802	蟺_蟺		wxid_wlxs9m0wmzat22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1803	娣′付		wxid_iz84hnjiytgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1804	闆?	wxid_jxf4rdl9klrl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1805	馃		wxid_p776rj2q37hi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1806	馃悜		wxid_2w0a22u4g1ju22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1807	娼滄按dive		wxid_ad7tr6k0grgz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1808	The king of forest		wxid_bo85km6cdide22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1809	閱夌敓姊︽		wxid_t2ve00cl95xe22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1810	澧?	wxid_jc3gfwsh5lg222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1811	wow鍝?	wxid_t380tzi75bqf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1812	锛?	wxid_yvzbrnmbptp622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1813	锠?	wxid_3kybhqntj7so22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1814	棣欏北澧ㄨ抗		wxid_slp5sz03um3e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1815	涓滄柟涔嬫棦鐧?	wxid_gwntvffrbmxe22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1816	鍗块工		wxid_hbnmp0bklzyg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1817	鍞炬搏鏄熷瓙		wxid_b6ak7p77ueyn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1818	JHC馃搱		wxid_hqx2crjip1l322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1819	涓€浣嶅尶鍚嶇綉鍙?	wxid_k2op349j4ahp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1820	Ubermensch		wxid_5ogbonrqs9di22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1821	钀?	wxid_gfbj8im9sqrv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1822	鍑変粙		wxid_38depm51z4z022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1823	浠?	wxid_v38azo6b2fqm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1824	S  Yt  Pt		wxid_h4zprgenizms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1825	鍗楀哺闈掓爛		wxid_s1g1xsjerdcf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1826	璇嵖婕?	wxid_i6n0fntcrk5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1827	鐖辩殑涓績杞?	wxid_uoplyelfsgbm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1828	鐜?	wxid_yir4aj3i52cc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1829	浜戝		wxid_qipi7zqvhsp922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1830	闆峰瓙鎵?	wxid_jrgf1tqdft8r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1831	鍥藉瓙灏?	wxid_kt3dheatjk3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1832	缇?	wxid_o6czd1p4e9f322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1833	鎴愬ぇ浜嬭€咃紝涓嶆嫆灏忓		wxid_yrei6dji2x5922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1834	鐏甸瓊鎹㈠績		wxid_taykjk0kok0622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1835	鏄熸渤娆茶浆鍗冨竼鑸?	wxid_z41fuz7j1e0d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1836	甯呮皵鐨勭敺瀛?	wxid_r49e1rk76gh222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1837	绔嬩簬宓╁北涔嬪穮		wxid_toh44abz0gon22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1838	鎴戝拰鍍靛案鏈変釜绾︿細		wxid_gbdgm5vqs9dr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1839	7		wxid_ohu13816qiri12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1840	YIN		wxid_pcjwc44is1pd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1841	閰锋礇绫?	wxid_wcrqcqq3an1j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1842	鑷搁嚜妯跺垵		wxid_y1zjzrjtyfw522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1843	閲婃€€		wxid_e39l7vs596h222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1844	鍚存澗宀?	wxid_j02qyj3byogc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1845	驴驴驴		wxid_eiq0vmi3xltn22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1846	鍛ㄨ崱		wxid_xqwl0px0nlbs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1847	鍚戜笂		wxid_s4o6l8d3e9y722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1848	绁炰篃澶氭儏鍚?	wxid_g6e27rwzj8p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1849	鑲栭摖缈?	wxid_ifn6gt1o75dy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1850	鑲嗙嚔		wxid_rhy4pv2dbq5t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1851	.		wxid_p9261xru5kxb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1852	閮佸叧		wxid_j90dysisjd6p22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1853	mask		wxid_69q9mtpfauyd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1854	椹瓧瀛?	wxid_s46xhf9cxid122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1855	qq		wxid_be8jpx6ambms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1856	灞辫尪鑺卞紑鍦ㄥ勾绯曢噷		wxid_y4cy397f0kbc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1857	o		wxid_71n0qc0g1kry22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1858	婵犳瘚浜烘€?	wxid_dkyjd8dwpg0d12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1859	褰共瀹?	wxid_mvm45f9h92m222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1860	Prince		wxid_s7vygnw1m92c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1861	Plantagenet		wxid_vinfm33n9vi722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1862	闅?	wxid_n98s00sa5sk622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1863	銆?	wxid_kwjp19gh95pq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1864	钃濇ˉpro		wxid_gks1a6pds5wy22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1865	濞?	wxid_1v3qp921k44422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1866	缃戠孩鏂囩鎵?	wxid_jsdyma643x8u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1867	banzhuan		wxid_losa2umzfhx422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1868	鍙舵涓?	wxid_wquadxvfdg2522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1869	鏄欏叜娴ⅵ		wxid_xbhfbhb3o3bt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1870	蕷鍑夊績蔀		wxid_lgy75vq5yu5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1871	鐓嗙刀		wxid_o4c87y0n5p2o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1872	姹よ嚕涓€鍝?	wxid_mv037xmzwo3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1873	鏁ｆ极銇缓绛戝		wxid_g4s5hyh0irs132	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1874	鍚涘瓙		wxid_hkf0d8hdbl0612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1875	闂綊鏈?	wxid_axxybvil5lmi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1876	A.灏忔稕		wxid_cmnv96lmolzz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1877	闆腑纰?	wxid_tnnp8it1ak5312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1878	鍜氬挌灏忓渾甯?	wxid_9x30fhf334ny22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1879	鍐插啿銆?	wxid_xuh3mw194mde22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1880	榄堢憻鐟?	wxid_eqdoqiu3rjqp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1881	闈掑矚.		wxid_lp3tqh3vtsnr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1882	Dan		wxid_xvasxbhgadcv12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1883	椋炵尓涓嶇敤楠戞壂甯?	wxid_40i7rxy1lytt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1884	H2O		wxid_ggnwo82td11322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1885	鏂版柊绔嬬媯鎯虫洸		wxid_v8h4k3ivnzyd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1886	鑺?	wxid_bulzqup2yga022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1887	Eliauk		wxid_gxfo8xzbp6aa32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1888	涓滃崡璺?	wxid_ezkd398r4vmb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1889	f		wxid_gsn5md6g6sag22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1890	wzh		wxid_iyjpc6frg71g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1891	寰″潅		wxid_lsnk0cy524ya22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1892	鍐伴湶		wxid_w2v4x7beaq8y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1893	favor		wxid_r9zzr1kcekoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1894	zero		wxid_yivzvnwq193b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1895	鏈辨尟浜?	wxid_umqh842jm9qm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1896	娑垫兜		wxid_2bofbptvp1l312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1897	瀹呮棩闂?	wxid_22ng0dr86f2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1898	醿?	wxid_c3kwk4thsidr32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1899	闀挎闈炲父鎱?	wxid_gt1bymvrydgc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1900	铔囧柊		wxid_2w2ff4rir8mp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1901	hide on bush		wxid_4223g3joodhp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1902	鑳¤儭鍥?	wxid_kzoccjre7kbm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1903	FIOO		wxid_ov9f23tppe8122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1904	Oahgond.		wxid_21q8ufzpuocl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1905	鍟婂搱锛燂紒		wxid_0dbdsn7t2vp22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1906	娉ュ湪骞蹭粈涔?	wxid_cmajcs41743i22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1907	椋庢竻		wxid_14og03h9i9cl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1908	澶у湴鐨勫勾杞?	wxid_y94xc6jkf5sb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1909	鏃跺€?	wxid_36h8x18nv0mm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1910	姝㈤洦鎭?		wxid_vx2sxr4hb4mv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1911	灏忕毊鐗硅嫃涓?	wxid_nyxkxd3urnv522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1912	hk		wxid_fqg6l5w3aazj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1913	涔﹀湪鑴镐笂		wxid_hf0gmhh82meh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1914	銆傘€?	wxid_kvx6uuatymbf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1915	鎬€妗?	wxid_3dctycwr6i9122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1916	閭ｆ垜璇ュ浣曟槸濂?	wxid_n3ckceqx68iv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1917	绉︾惔.		wxid_3zpzpqq0t16922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1918	灏榓h.		wxid_xysi66chormi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1919	绛圭埖鏃?	wxid_k1dy6gv4m4n822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1920	澧ㄨ瘔		wxid_bftlsalvquuz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1921	鍢垮樋		wxid_vdhem3j2h0wc21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1922	Cai		wxid_gkepckijlna322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1923	涔﹀北鍘嬪姏澶?	wxid_4ygxwe7syj9u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1924	榄斿厠鎷夊杈硅礉		wxid_xvpyw1fap54h22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1925	鎴戞兂蹇?	wxid_xq3ag3zi5m8o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1926	zy		wxid_spdlfhuzbza322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1927	缇婅倝鏀?	wxid_1q6ena9q1tl222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1928	娴敓		wxid_hktrb5vcwtzj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1929	鏉庡お榛?	wxid_aeoixzi7ipoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1930	闇娈?		wxid_p8d83809eaye22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1931	鐗电潃铓傝殎鍘绘暎姝?	wxid_jiwzy590z0f722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1932	Levi		wxid_j7cte0xrmkkg12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1933	姹熸禂		wxid_2nse6w4tnb6m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1934	馃		wxid_4j5bb78bq17m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1935	鍙?	wxid_rshpdppcmr6w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1936	馃槆		wxid_a0d5w1yayt8e22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1937	鑺滄箹		wxid_ql170ameiv2v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1938	纾?	wxid_jo6ohv64x83b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1939	浣犵殑榧诲瓙鏈変袱涓瓟		wxid_t7yhq7x9y1iv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1940	鏍规湰鐫′笉閱?	wxid_jisseh8swktq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1941	缁电坏		wxid_qjy33gyyq5tk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1942	The One		wxid_z2nbvhamyc5g21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1943	姹惫		wxid_5aqm8mwf5ezq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1944	钃濇捣		wxid_995dr1ztukj422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1945	椴佹爲浜?	wxid_ulqdl0d0hdxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1946	J.		wxid_z5w05o6wcsp322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1947	嗉€嘟樴綆嘟侧綌嘟戉鲸嘟亨涧鍏█		wxid_u83p6zokot1w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1948	閮藉競澹瑰瑁? 渚旦		wxid_as3x9332ncea22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1949	鏌掓湀		wxid_tk1hq3zuthug12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1950	绌?		wxid_zxfw2j6zr3ye22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1951	鑽ｈ崳		wxid_7ekmd1yib8eh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1952	甯屾湜浜烘病浜?	wxid_x6gnhsqwgx5w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1953	榫氬叕瀛?	wxid_fbr19uajo6db12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1954	鏂瑰皬缇?	wxid_vd5bo57rqbfg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1955	鍛ㄤ竴楦?	25984982801828156@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1956	骞村皯绔嬪織涓夊崈閲?	wxid_e67hnzfgyekq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1957	鏆洩鐚胯釜		wxid_2knhoyggmr7s22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1958	绉︾帇鏀?	wxid_njz9gmidd3ag22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1959	鑺?	wxid_r0cgjliaup9x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1960	娲涚		wxid_o7uly0p9gk4u22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1961	涔濆笀		wxid_8lt64a5rs4th22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1962	鎴忚		wxid_krragij21wv522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1963	瑷撳ソ鍚冨ソ蹇冩儏濂?	wxid_cqxxhxiocbi812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1964	缈?	wxid_uk9xuagm78rl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1965	鏄?	wxid_770r1lj9iiri22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1966	鑲嗙劇瑾嬭瓊		wxid_5rn81u91nmhl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1967	浼氬姩鐨勫悜鏃ヨ懙馃尰		wxid_bt1izbdmaj7v22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1968	鍚磋禌淇?	wxid_febp1gtmko9711	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1969	浠婃棩灏忛洦杞櫞		wxid_9l2o8dh323rv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1970	鎵惰嫃鑽峰崕		wxid_piw69h8a163o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1971	CAP		wxid_eadhjjx53ftu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1972	闃嗘湀閭€椋?	wxid_eik2qtn4b06922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1973	Eason		wxid_zfcwv830cg3122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1974	2.28 15:30銆婃棤鍚嶄箣鐢恒€嬸煄?	58258014111@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1975	cd		cd838181651	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1976	榻愬ぉ		wxid_8km3t0gvu51g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1977	閭撹瘲鏅?	wxid_2mlxppghq4tk52	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1978	涓夊垏鍏嬨伄濡冨		wxid_7lmers687e3822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1979	A  涓夊垏鍏婼anCheck		wxid_x1wrbijh53w212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1980	鎬濇灉鍠勮礉濞滃鑾?	ga2041	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1981	A鎱х敤蹇冭储绋?鐔婇		wxid_fpq4dttfgynk22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1982	鐔婇		25984983182468490@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1983	鍒樺厜鏉?	25984983561986652@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1984	鏉庣拹鐟?	25984983747528898@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1985	鑲栭洴		25984984258066829@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1986	椴滆€€鎱?	25984985671370223@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1987	鎴愰兘-璐㈢◣鍔╃悊-鑺姱		wxid_2b2bdev9n9lw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1988	58122017019@chatroom		58122017019@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1989	瑗垮崡绉戞妧澶у鍩庡競瀛﹂櫌娈哄弸闆嗙粨绀?	48454906001@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1990	寰瑧		wxid_6fx8ph5dfnod22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1991	鍚洦		wxid_b4qpmzap4mad22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1992	顛?鏋滅矑杈?顛?	wxid_l53fl0r7y0ye11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1993	宀佹湀濡傛瓕		wxid_0g8jyr1mid5q22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1994	骞哥涓€鐢?	wxid_gfu8mwnyj5g322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1995	Leon_YL		wxid_kj8cf97d0dws22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1996	@HHH		wxid_5x1ukkcmluwo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1997	鏈堜笅鎷惧厜		Tobyna	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1998	鏋楁湪瀛?	wxid_c9za31tpbh9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
1999	铚楃墰		wxid_ktq85r0onsry22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2000	绂忓涓滄捣		wxid_6ned0pol69tu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2001	闈掓槬涔嬫瓕		wxid_sz2kj8zuwvo322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2002	绂忓涓滄捣		wxid_31nm7gzt30si22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2003	鑰佷經鐖?	wxid_m09s5gtd542c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2004	榄旀硶娴疯灪		wxid_gmmah2wvpzd112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2005	瑗块儕鏃犲瘑鏋?	wxid_xlwysw5blhhs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2006	Keep going		wxid_wmzdk60c00g612	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2007	姊︽兂鏃跺垎		wxid_u4j6lxigeyeq12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2008	000		wxid_qd8yxly7x2ye22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2009	Missing Persons 1&2		wxid_dwd22wh5ova022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2010	鏃?	wxid_79ztlygf5e9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2011	浠婂畨鍦?	wxid_oyy6vgh9mhdb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2012	鍏堣鑰?鍙?	wxid_z9qcajalc8or22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2013	闃冲厜灏戝勾		wxid_5w4hbbrx64z622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2014	L		wxid_bs0w56io6xa622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2015	瀹佹槬寤垮叓		wxid_gmc65jvaao5t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2016	鍥涘窛鏍℃姎鍙?灏忚帿		25984985466886554@openim	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2017	澧冪晫		50511686015@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2018	灞曠ず涓庨檲鍒?	45204834600@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2019	灏忓厰瀛愪箹涔?	wxid_hwazt1ro9y0322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2020	鏈嬪弸鍦堝箍鍛婃暟鎹悓姝ュ鐢ㄨ处鍙?9		gh_aa323b423238	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2021	涓浗浜烘皯澶у		gh_0ce99180d8d1	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2022	鍖椾含澶у		gh_35de600bac75	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2023	鏈嬪弸鍦堝箍鍛婃暟鎹悓姝ュ鐢ㄨ处鍙?7		gh_f48bc3f0ccbb	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2024	鐝犵﹩鏈楃帥宄?	24959224106@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2025	缇庢湳鍐插啿鍐?	43676976174@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2026	鏆戝亣绉佸瘑浜ゆ祦缇?	23803436001@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2027	钂?1		wxid_kix4hyd0r2nl12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2028	钖勫阀鐢滅敎鍦?	wxid_9m890ydg4gud22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2029	涓夊浗鏉€璁ㄨ缇?	47514547828@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2030	楂?020绾х編鏈兢 楂樹笁缇庢湳2023		24861687870@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2031	鍦扮悊鐭ヨ瘑灏忚鍫?	23604594208@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2032	銆愮粨钀ョ彮浼氥€戝崄鏂硅棰戝壀杈慙373		43137195470@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2033	鐐告ⅷ閰?	wxid_t0raa32nqt4n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2034	浜虹敓灏辨槸鍦熻眴bot		wxid_zi4e61rddwro22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2035	鏄岄箯鏄撶粡鏂囧寲		wxid_b6xqp96n4hmo12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2036	鎴戜笉缁囧€?	wxid_swaywapuhk3u32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2037	锛燂紵锛?	wxid_k2mb5q8tj3aq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2038	YZ		wxid_ih4bi6am09tq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2039	馃憖		wxid_rv7wq406cuya11	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2040	灏忕嫍琚晝娉?	wxid_smt6qlca0w3y12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2041	鍗庨		wxid_4zddccrli8zd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2042	寤栧浗鍑?	wxid_0z0wdj9kutok22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2043	浠婂ぉ娌℃湁鎶?2		wxid_jyqln93wma2m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2044	49267277248@chatroom		49267277248@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2045	48804970357@chatroom		48804970357@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2046	涓€骞翠竴搴﹀浗搴嗗簲鎻村洟		38806123364@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2047	bee鍔ㄦ极鍓緫绀?	43499996781@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2048	-		wxid_jejr0dpn5kml22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2049	ST.		wxid_oorpeppwe44122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2050	鏅婃仸		wxid_0iu2chvwtirf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2051	鏌冲洜椋庤捣		wxid_18scsoy5my422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2052	琛岃€?	wxid_qne18y5ssvi122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2053	49706163011@chatroom		49706163011@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2054	34553110083@chatroom		34553110083@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2055	鎵嬪啓鍗板埛搴?	43095916074@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2056	馃搷24缁靛煄 鏂板獟浣?鐝娓歌瘉鍜ㄨ缇?	49297378373@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2057	鈿狅笍绉佽亰鐐硅繖涓殸锔忔捣鑳嗘壒鍙戝競鍦?	34556155518@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2058	灏忕墰椹?	34710495432@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2059	灏忓		wxid_ubjyobvmqu8k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2060	娲炴礊瀛╅摑鐜?锞熛夛緹)		wxid_58o9671u1qta22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2061	澶忚€佸笀		wxid_sktq76qqpdka22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2062	缃楄€佸笀馃巰		wxid_gowtnhlqip9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2063	濡勫徃		wxid_cddbfmgzaczj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2064	Nil		wxid_jp03mon19kh222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2065	Z.L.X		wxid_tz3przqvggek22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2066	yHy		wxid_ajiiln9td4gj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2067	鏄伒涓嶆槸鐜?	wxid_ppm0xtqi4lml22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2068	lcy		wxid_zj5cfcev8uo22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2069	4OO		wxid_tj862rab5uwb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2070	绾?	wxid_8drwlvpizea322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2071	顏?	wxid_uu7no1mdqfzm22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2072	WAkeeeUp		wxid_0jrup3kv4bgc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2073	snowy		wxid_nlg1k7ik0sil22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2074	娆?	wxid_b9s339b08yuj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2075	Jannifer		wxid_258xqv5orv2i12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2076	缁濈編鍝堝＋濂?	wxid_6g9a2uo4zj0a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2077	Yuna&L		wxid_ahquvku32plc12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2078	Spicy		wxid_b0wv2e0pay8r22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2079	46090785316@chatroom		46090785316@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2080	鍒樻亽鍎縞os鐏?	39027687672@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2081	铓傝殎馃悳		47327306014@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2082	UNO涓€涓?	48839360625@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2083	缁靛煄瀹樻柟闈掓槬鐗?瀹樻柟闈掓槬鐗?49357688596@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2084	49244791622@chatroom		49244791622@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2085	42969942736@chatroom		42969942736@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2086	涓崕鍛抽亾.cn棣欐皼绮変笣绂忓埄缇?	18664747123@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2087	45669012886@chatroom		45669012886@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2088	GNED		wxid_fpffk4sbwmtx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2089	鍙栦釜鍚嶅瓧鐪熼毦		wxid_n4qlfzs0gc7c22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2090	AIMPD		wxid_1qglk0trnj5d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2091	婢?	wxid_mhr6g8r27poa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2092	7.		wxid_54yh7titj2ft22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2093	寤?	wxid_gfmmobdxhzxu22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2094	+v鐪嬭煿榛勫牎绉樻柟		wxid_wihixswbwui422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2095	鍙跺悰妗?	dannyedan	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2096	楂樺皬闆?	zhutouya1218	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2097	鎷夌編瑗挎柉灏忕帇瀛愷煓?	wxid_iemyb1ndgjq621	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2098	锝?	a38221417	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2099	鍗婅		wxid_v3zc5r2m5t2822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2100	涔栧路宄ㄧ湁灞遍櫔鐖憚褰甭峰ソ鐗╁垎浜?	wxid_8265bw8zu5fq21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2101	鑾笂		moxuyou1212	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2102	鐢熺敓		wxid_2048jisoxhcs21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2103	鍗楁爛		wxid_avs0sel50d5d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2104	Barnett		wxid_iqmw5tclrmon22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2105	鏉庢€兼€?锛堟鍦ㄥ噺鑲ョ増锛?	wxid_8i6xg6zho9rf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2106	姹夎祻APP.灏忕▼搴?鍗庢湇琛屼笟鎶€鑳藉煿璁?		wxid_uwnbhouygse022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2107	闈欏績瀹佺		wxid_lphc13v0bn9u21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2108	鍊惧鐏?	wxid_1shralzy4o6f21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2109	鏃烘椇		wxid_4lqz135bnwls22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2110	鑻ョ氦		wxid_5nedznc5idzj21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2111	钖涘旦鐨?	wxid_7qqis0cnw7gz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2112	钀芥爛		wxid_5j47kpeld4aa22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2113	銆?	wxid_1c6w893rgnzq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2114	灏忕偖鐐偖馃槝		small_lucky	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2115	路釡娐?	wxid_wry93b4gim3o12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2116	hao123		wxid_77gaw9epin3o22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2117	澶浜?	wxid_x1pm9x63fwoq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2118	宄ㄧ湁鏀€鐧婚璺汉-灏忎箹濞楨MS		wxid_g67zpfi6q36m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2119	宀涘笨鏅ㄩ搩.		wxid_2rbhikuk790a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2120	Eos.C褰╃幉鏅颁簯		wxid_enf4zjiv3k2i22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2121	鏃烘椇纰庡啺鍐?	wxid_xvx3c1bd8upt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2122	鏁呮ⅵ		wxid_dq06q0tv2jq222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2123	鍚涗笉鍚?	wxid_19n2rsbamgr522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2124	灏忔堡鍦?	wxid_4jgvtoeb47wc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2125	鏃х		wxid_wfmgbf6jhpsx22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2126	鐭ヨ浠?	wxid_rq8ycmespt4k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2127	鍚戦槼鑰岀敓涓?	wxid_ss6yrhbhl2s822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2128	鑹剧绉?	wxid_h2d80zxwdhe722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2129	闆峰瓙鏋?瀛靛寲鍋ュ悍涓绘挱娴侀噺鍙樼幇		wxid_6151941517211	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2130	瑭圭伯鐟楋紙瑭圭幉锛?	zhanling302	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2131	銆?	wxid_ovtabr07gtvc21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2132	鑺濆＋		wxid_6213162133912	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2133	鑰佽枦鍟?		wxid_s741alg49oe722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2134	闃夸附		wxid_l83vtiu3h5n522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2135	鐏?	wxid_v4yob2oj0kkq21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2136	oceantea		a39522000	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2137	濂藉ソ		wxid_j4ap7i8lb86922	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2138	澶变箣鎴戝懡		wxid_5vw7ymmlxfpt22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2139	榛勫ぇ鐐?	wxid_6322273222421	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2140	鏉庝匠璇?钃濈櫧涓撳睘鍞悗缇?	38878474889@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2141	鑰冪爺鐝嫳璇涔犵兢		48045280779@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2142	鎴愰兘wagons鍏夐€熻秴璺戠鍒╃兢		25001268018@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2143	瓒呰嚜鐒堕櫔鐜╃兢1		57719503612@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2144	寮?	wxid_2svmkgqlbn9421	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2145	bbbq		hbq80406326	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2146	LJH		wxid_gxmgzdra1mt312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2147	lemon麓		wxid_lh4ubcakwvlc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2148	Mr.forgettable		wxid_en7lb24qjq9k12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2149	閾冪鐧惧悎瀛?	wxid_6duowys6xtat22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2150	Z1rannn.		wxid_s7e6vb3v7k8l32	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2151	鍑涘啲鏌掑簭		wxid_9w6vbfhrr6cs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2152	Pearl.L.H.		wxid_ec8psbknz0ya22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2153	鎶氬噷		wxid_0hvmbvwl8as122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2154	Komorebi		wxid_83zp1bx6o6se22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2155	杩欑		wxid_t1d0co6actkq12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2156	KanekiKen		wxid_d79570wzi9vz12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2157	Royee		wxid_kjz6evva8x8422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2158	-C鈧塇鈧佲倝		wxid_g7li4qlx9i9k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2159	鎭掔憺		wxid_dz4eojlkk6ms22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2160	tttttt		wxid_egonivwt5z3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2161	mike		aabbcc11223314	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2162	wagons007		wxid_e8n3uvv3v5x112	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2163	GTAuto 宸?	wxid_wege9qjh38n521	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2164	FFF		fxy13191147888	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2165	Y.		c912507426	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2166	澶忛粯		wxid_3137451371012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2167	L W H		wxid_e6q9jw5l6qwy12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2168	椋庤捣浜戝竼		wxid_3gga27mbmhcl22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2169	鏉庢案绁?	wxid_lapstx5dlp1w22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2170	Zono馃尒		wxid_637vh6bubcvf22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2171	YHC-鍚戞棩钁?	wxid_4h7pepw2ewdr12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2172	Simon Go		ding779108012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2173	涓€鍒囬殢椋?	wxid_hkipedbo0kw822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2174	鍙哥惇Sisi		sqkinow	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2175	Calvin.C		ck563452945	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2176	涔橀緳閲嶅崱		wxid_gm5f1jgmhv6s21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2177	釚囮珋岌佱枃戢€		lyx7758	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2178	馃馃専		wxid_s2yxj6thyush22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2179	77		king958560835	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2180	OK馃専		you057979	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2181	涔愪韩浜虹敓		wxid_ps4kgxuiaz2l22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2182	lron man		wxid_q70lec0673aa12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2183	鐑備汉		wxid_01ui0pdj2s7s21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2184	澶ч煶		vitons	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2185	Kevin 鲁鲁闄冲織娴?	Q276393231	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2186	KingFy		wxid_52rqn5hite5312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2187	鑸归暱		wxid_ill60h4wj3mv22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2188	涓嶆€?	feixiaozhang	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2189	鏂囧垈鍒?	LDLY88888888	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2190	搴峰悍		huyanglovetmh	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2191	銆?	wxid_9rrwbn78qrjq22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2192	璋緳		stop123	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2193	钁涢噾铏庣殑鐖哥埜15371399292		wxid_3h3oafqpvm9x22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2194	R贸sa鍑や竷		wxid_ukb21lcyng9a22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2195	KF绉戝嚒楂樺畾锝滆€佽帿		yqlzle	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2196	寮犳稕		wxid_z7vpaxrvv6cc21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2197	姗樺瓙馃崐		wxid_d1uxk8i4hnz322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2198	闃跨攳馃檶锛堣繘闃剁増锛?	wxid_u2zi22pa6qfg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2199	钄撹敁馃挮		wxid_3654366543812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2200	馃悑		wxid_qe3us5mmba1m12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2201	brisbane鐫ｅ		wxid_6iw68dfskpmi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2202	Z		zhangningone123	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2203	鏃╁畨		wxid_esyeagom1d3b22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2204	鏉ㄩ暅鐢帮紙浜屾墜杞?鎶艰溅鏀炬锛?	q397538772	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2205	鍛ㄧ嚉  钄氭潵涓撹惀 璞溅 杞﹂櫓		wxid_311kjya9yv2l12	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2206	Alprazolam.		wxid_qsyg77p7b9t422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2207	灏忎節		wxid_6x7qxj96oejh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2208	姘村厛鐢熺殑鍛嗘瘺		wxid_2ua5s8e14x0q21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2209	Paolo		wxid_2853408533812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2210	-		wxid_bmf1od11ommy21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2211	鍗佷竷		wxid_ovob6uuj0mfd22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2212	涓夊厓		wxid_kwo35yaomzr822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2213	Elf		wxid_fr72wb1uudw812	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2214	鍝燂綖		jfyx123456	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2215	鐖卞悆楹﹀綋褰?	wxid_mdle92eht59k22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2216	鍖楄景		wxid_86v3hrvgjoxr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2217	楠戜笂鎴戝績鐖辩殑灏忔懇鎵?	wxid_xwnevw2few6222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2218	釢瓣珱戢€戟?	wxid_rsqqor0rdfnr22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2219	澶х櫧鑿?	wxid_ay6nf13etksh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2220	澶忓ぉ		wxid_5nhwbbjzz81g21	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2221	缇庡紡杩樻槸寰楀姞鍐?	wxid_xc0ou2j3zyed22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2222	铏?	wxid_cjsxyjbje4wi22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2223	鐠愮拹		wxid_275nxjztxi3y22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2224	45711206363@chatroom		45711206363@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2225	鍒佹瘺浜ゆ祦缇?	49683879816@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2226	璁ㄥ帉浣滀笟馃挃		50641071171@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2227	48161301382@chatroom		48161301382@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2228	绂佹瘨鐢靛奖銆婂洖涓嶆潵銆?	45934920121@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2229	2+3=5锛堜釜鍒佹瘺锛?	49590500283@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2230	鍙屽懆鍛ㄤ簩涓嬪崍7.8鑺傚煄甯傚闄?	48095168434@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2231	43464445438@chatroom		43464445438@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2232	濂界殑		wxid_5179431792913	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2233	鏃跺磶		wxid_qfp4ztubyti122	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2234	Nancy		wxid_8cy4x5vd7jrs22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2235	灏忈硱楸坚硱 喋?	wxid_cqk4axr5bj5n22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2236	浜?	wxid_ujm548m75i8422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2237	LL.		wxid_qbjez2hrejzg22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2238	闆炬担.		wxid_pq7epv6sxmg522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2239	鏋滃喕姗?	wxid_cg7fv4mg6k0012	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2240	鍥界帇		wxid_6k935khkwgh522	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2241	77Luu_		wxid_mjou9wb5g60d22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2242	LikL		wxid_fys03tbxei6t22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2243	badada		wxid_b93yzumx8df022	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2244	鏄ュ簭棰?	wxid_lxyrcgz8cclj22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2245	褰煢?	wxid_aw0o05xilqsh22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2246	lovex		wxid_2npp8oybh5vc22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2247	宀佸瞾瀹?	wxid_u9jl0liqof2m22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2248	Aloha.		wxid_f42j0zz6vnqz22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2249	鏍告鏄熸槦缇?	wxid_96wuwtu4392s22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2250	馃挙		wxid_sj9ri2ql6k5g22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2251	11		wxid_oyj1hlrdjcc222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2252	Atopos		wxid_zbphfjpa1mgw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2253	宀?		wxid_u8dcap68r06322	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2254	閭伓榛勯紶鐙?	wxid_1ifof3w11jdb22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2255	涓€鏈甸涓憞鏇崇殑缇婄毊搴曢檲淇婄敓		wxid_dxds09zvi4w222	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2256	璞嗗柕鍠?	wxid_f2t6rzdnw76j22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2257	涓嶇槮鍒?20涓嶆敼鍚?		wxid_ydlek0xsgor822	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2258	绌虹帴		wxid_5i2gwe2zatpw22	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2259	瀹夊窞鍩庡競瀛﹂櫌蹇冪悊鍋ュ悍2鐝?	47760370211@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2260	澹瑰姞澹逛紭閫夊洟璐兢(澶钩鍥?		39157462288@chatroom	group	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2261	灏忚緣		wxid_k01qen0c8wj722	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2262	涓嶇煡閬撴槸鎰熷簲闂ㄦ墍浠ョぞ姝讳簡		wxid_0dfjww8bvh9422	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2263	涓滄柟绾?	wxid_5064780647312	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2264	鏈嬪弸鍦堝箍鍛婃暟鎹悓姝ュ鐢ㄨ处鍙?6		gh_7d8eb298e1e2	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2265	鏈嬪弸鍦堝箍鍛婃暟鎹悓姝ュ鐢ㄨ处鍙?5		gh_b16d6afed604	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2266	Julien02161		wxid_woqdozid4n0622	contact	1	0	2026-03-24 15:15:14	2026-03-27 00:20:40.315225
2267	鐧介緳椹琟_^鏉庣鏋?	wxid_x6cvsq9ao94722	contact	1	1	2026-03-25 12:29:37.899333	2026-03-27 00:20:40.315225
2268	瀹嬭帀		25984983281050806@openim	contact	1	0	2026-03-26 04:02:27	2026-03-27 00:20:40.315225
2269	寰俊ClawBot		mmo9cq8067CybGXLSdOkdY-U4PC_wY@weclaw	contact	1	0	2026-03-26 12:31:32	2026-03-27 00:20:40.315225
46	鈩掟煉曗儴戟ゅ揩涔愷煂堟椂鍏夃獔嗫?	a40002396	contact	1	1	2026-03-24 15:07:26	2026-04-17 17:40:08.718453
\.


--
-- Data for Name: wechat_tasks; Type: TABLE DATA; Schema: public; Owner: xcagi
--

COPY public.wechat_tasks (id, contact_id, username, display_name, message_id, msg_timestamp, raw_text, task_type, status, last_status_at, created_at, updated_at) FROM stdin;
\.


--
-- Name: ai_action_audit_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.ai_action_audit_id_seq', 5, true);


--
-- Name: ai_conversation_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.ai_conversation_sessions_id_seq', 4, true);


--
-- Name: ai_conversations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.ai_conversations_id_seq', 10, true);


--
-- Name: approval_delegations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.approval_delegations_id_seq', 1, false);


--
-- Name: approval_flow_nodes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.approval_flow_nodes_id_seq', 24, true);


--
-- Name: approval_flows_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.approval_flows_id_seq', 13, true);


--
-- Name: approval_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.approval_records_id_seq', 14, true);


--
-- Name: approval_requests_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.approval_requests_id_seq', 9, true);


--
-- Name: distillation_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.distillation_log_id_seq', 1, false);


--
-- Name: extract_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.extract_logs_id_seq', 1, false);


--
-- Name: inventory_ledger_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.inventory_ledger_id_seq', 1, false);


--
-- Name: inventory_transactions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.inventory_transactions_id_seq', 1, false);


--
-- Name: mp_addresses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_addresses_id_seq', 1, false);


--
-- Name: mp_browse_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_browse_history_id_seq', 1, false);


--
-- Name: mp_carts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_carts_id_seq', 1, false);


--
-- Name: mp_favorites_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_favorites_id_seq', 1, false);


--
-- Name: mp_feedbacks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_feedbacks_id_seq', 1, false);


--
-- Name: mp_notifications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_notifications_id_seq', 1, false);


--
-- Name: mp_order_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_order_items_id_seq', 1, false);


--
-- Name: mp_orders_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.mp_orders_id_seq', 1, false);


--
-- Name: permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.permissions_id_seq', 1, false);


--
-- Name: products_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.products_id_seq', 1445, true);


--
-- Name: purchase_inbound_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.purchase_inbound_items_id_seq', 1, false);


--
-- Name: purchase_inbounds_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.purchase_inbounds_id_seq', 1, false);


--
-- Name: purchase_order_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.purchase_order_items_id_seq', 1, false);


--
-- Name: purchase_orders_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.purchase_orders_id_seq', 1, false);


--
-- Name: purchase_units_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.purchase_units_id_seq', 33, true);


--
-- Name: roles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.roles_id_seq', 1, false);


--
-- Name: shipment_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.shipment_records_id_seq', 1, false);


--
-- Name: storage_locations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.storage_locations_id_seq', 1, false);


--
-- Name: suppliers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.suppliers_id_seq', 1, false);


--
-- Name: template_usage_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.template_usage_log_id_seq', 1, false);


--
-- Name: templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.templates_id_seq', 1, false);


--
-- Name: training_stats_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.training_stats_id_seq', 1, false);


--
-- Name: user_memories_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.user_memories_id_seq', 1, false);


--
-- Name: user_preferences_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.user_preferences_id_seq', 1, false);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.users_id_seq', 1, false);


--
-- Name: warehouses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.warehouses_id_seq', 1, false);


--
-- Name: wechat_contact_context_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.wechat_contact_context_id_seq', 1, false);


--
-- Name: wechat_contacts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.wechat_contacts_id_seq', 8, true);


--
-- Name: wechat_tasks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: xcagi
--

SELECT pg_catalog.setval('public.wechat_tasks_id_seq', 1, false);


--
-- Name: ai_action_audit ai_action_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_action_audit
    ADD CONSTRAINT ai_action_audit_pkey PRIMARY KEY (id);


--
-- Name: ai_conversation_sessions ai_conversation_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversation_sessions
    ADD CONSTRAINT ai_conversation_sessions_pkey PRIMARY KEY (id);


--
-- Name: ai_conversation_sessions ai_conversation_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversation_sessions
    ADD CONSTRAINT ai_conversation_sessions_session_id_key UNIQUE (session_id);


--
-- Name: ai_conversations ai_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversations
    ADD CONSTRAINT ai_conversations_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: approval_delegations approval_delegations_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_delegations
    ADD CONSTRAINT approval_delegations_pkey PRIMARY KEY (id);


--
-- Name: approval_flow_nodes approval_flow_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flow_nodes
    ADD CONSTRAINT approval_flow_nodes_pkey PRIMARY KEY (id);


--
-- Name: approval_flows approval_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flows
    ADD CONSTRAINT approval_flows_pkey PRIMARY KEY (id);


--
-- Name: approval_records approval_records_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_pkey PRIMARY KEY (id);


--
-- Name: approval_requests approval_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);


--
-- Name: distillation_log distillation_log_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.distillation_log
    ADD CONSTRAINT distillation_log_pkey PRIMARY KEY (id);


--
-- Name: document_templates document_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.document_templates
    ADD CONSTRAINT document_templates_pkey PRIMARY KEY (id);


--
-- Name: document_templates document_templates_slug_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.document_templates
    ADD CONSTRAINT document_templates_slug_key UNIQUE (slug);


--
-- Name: excel_vector_chunks excel_vector_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.excel_vector_chunks
    ADD CONSTRAINT excel_vector_chunks_pkey PRIMARY KEY (chunk_id);


--
-- Name: excel_vector_indexes excel_vector_indexes_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.excel_vector_indexes
    ADD CONSTRAINT excel_vector_indexes_pkey PRIMARY KEY (index_id);


--
-- Name: extract_logs extract_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.extract_logs
    ADD CONSTRAINT extract_logs_pkey PRIMARY KEY (id);


--
-- Name: inventory_ledger inventory_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_ledger
    ADD CONSTRAINT inventory_ledger_pkey PRIMARY KEY (id);


--
-- Name: inventory_transactions inventory_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_pkey PRIMARY KEY (id);


--
-- Name: mp_addresses mp_addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_addresses
    ADD CONSTRAINT mp_addresses_pkey PRIMARY KEY (id);


--
-- Name: mp_browse_history mp_browse_history_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_browse_history
    ADD CONSTRAINT mp_browse_history_pkey PRIMARY KEY (id);


--
-- Name: mp_carts mp_carts_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_carts
    ADD CONSTRAINT mp_carts_pkey PRIMARY KEY (id);


--
-- Name: mp_favorites mp_favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_favorites
    ADD CONSTRAINT mp_favorites_pkey PRIMARY KEY (id);


--
-- Name: mp_feedbacks mp_feedbacks_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_feedbacks
    ADD CONSTRAINT mp_feedbacks_pkey PRIMARY KEY (id);


--
-- Name: mp_notifications mp_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_notifications
    ADD CONSTRAINT mp_notifications_pkey PRIMARY KEY (id);


--
-- Name: mp_order_items mp_order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_order_items
    ADD CONSTRAINT mp_order_items_pkey PRIMARY KEY (id);


--
-- Name: mp_orders mp_orders_order_no_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_orders
    ADD CONSTRAINT mp_orders_order_no_key UNIQUE (order_no);


--
-- Name: mp_orders mp_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_orders
    ADD CONSTRAINT mp_orders_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_code_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_code_key UNIQUE (code);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: purchase_inbound_items purchase_inbound_items_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items
    ADD CONSTRAINT purchase_inbound_items_pkey PRIMARY KEY (id);


--
-- Name: purchase_inbounds purchase_inbounds_inbound_no_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds
    ADD CONSTRAINT purchase_inbounds_inbound_no_key UNIQUE (inbound_no);


--
-- Name: purchase_inbounds purchase_inbounds_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds
    ADD CONSTRAINT purchase_inbounds_pkey PRIMARY KEY (id);


--
-- Name: purchase_order_items purchase_order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_order_items
    ADD CONSTRAINT purchase_order_items_pkey PRIMARY KEY (id);


--
-- Name: purchase_orders purchase_orders_order_no_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_order_no_key UNIQUE (order_no);


--
-- Name: purchase_orders purchase_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_pkey PRIMARY KEY (id);


--
-- Name: purchase_units purchase_units_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_units
    ADD CONSTRAINT purchase_units_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: shipment_records shipment_records_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.shipment_records
    ADD CONSTRAINT shipment_records_pkey PRIMARY KEY (id);


--
-- Name: storage_locations storage_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.storage_locations
    ADD CONSTRAINT storage_locations_pkey PRIMARY KEY (id);


--
-- Name: suppliers suppliers_code_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_code_key UNIQUE (code);


--
-- Name: suppliers suppliers_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_pkey PRIMARY KEY (id);


--
-- Name: template_usage_log template_usage_log_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.template_usage_log
    ADD CONSTRAINT template_usage_log_pkey PRIMARY KEY (id);


--
-- Name: templates templates_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.templates
    ADD CONSTRAINT templates_pkey PRIMARY KEY (id);


--
-- Name: training_stats training_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.training_stats
    ADD CONSTRAINT training_stats_pkey PRIMARY KEY (id);


--
-- Name: mp_browse_history uq_mp_browse_user_product; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_browse_history
    ADD CONSTRAINT uq_mp_browse_user_product UNIQUE (user_id, product_id);


--
-- Name: mp_carts uq_mp_cart_user_product; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_carts
    ADD CONSTRAINT uq_mp_cart_user_product UNIQUE (user_id, product_id);


--
-- Name: mp_favorites uq_mp_fav_user_product; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_favorites
    ADD CONSTRAINT uq_mp_fav_user_product UNIQUE (user_id, product_id);


--
-- Name: user_memories user_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.user_memories
    ADD CONSTRAINT user_memories_pkey PRIMARY KEY (id);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: warehouses warehouses_code_key; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.warehouses
    ADD CONSTRAINT warehouses_code_key UNIQUE (code);


--
-- Name: warehouses warehouses_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.warehouses
    ADD CONSTRAINT warehouses_pkey PRIMARY KEY (id);


--
-- Name: wechat_contact_context wechat_contact_context_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_contact_context
    ADD CONSTRAINT wechat_contact_context_pkey PRIMARY KEY (id);


--
-- Name: wechat_contacts wechat_contacts_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_contacts
    ADD CONSTRAINT wechat_contacts_pkey PRIMARY KEY (id);


--
-- Name: wechat_tasks wechat_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_tasks
    ADD CONSTRAINT wechat_tasks_pkey PRIMARY KEY (id);


--
-- Name: idx_document_templates_legacy_sqlite_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE UNIQUE INDEX idx_document_templates_legacy_sqlite_id ON public.document_templates USING btree (legacy_sqlite_id) WHERE (legacy_sqlite_id IS NOT NULL);


--
-- Name: idx_document_templates_role; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_document_templates_role ON public.document_templates USING btree (role);


--
-- Name: idx_document_templates_role_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_document_templates_role_active ON public.document_templates USING btree (role, is_active);


--
-- Name: idx_excel_vector_chunks_embedding; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_excel_vector_chunks_embedding ON public.excel_vector_chunks USING ivfflat (embedding public.vector_cosine_ops);


--
-- Name: idx_excel_vector_chunks_index_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_excel_vector_chunks_index_id ON public.excel_vector_chunks USING btree (index_id);


--
-- Name: idx_flow_key_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_flow_key_active ON public.approval_flows USING btree (flow_key, is_active);


--
-- Name: idx_intent; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_intent ON public.distillation_log USING btree (intent);


--
-- Name: idx_request_node; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_request_node ON public.approval_records USING btree (request_id, node_order);


--
-- Name: idx_template_usage_log_template_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_template_usage_log_template_id ON public.template_usage_log USING btree (template_id);


--
-- Name: idx_templates_type_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_templates_type_active ON public.templates USING btree (template_type, is_active);


--
-- Name: idx_used; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_used ON public.distillation_log USING btree (used_for_training);


--
-- Name: idx_users_is_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX idx_users_is_active ON public.users USING btree (is_active);


--
-- Name: ix_approval_delegations_delegate_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_delegations_delegate_id ON public.approval_delegations USING btree (delegate_id);


--
-- Name: ix_approval_delegations_delegator_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_delegations_delegator_id ON public.approval_delegations USING btree (delegator_id);


--
-- Name: ix_approval_delegations_is_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_delegations_is_active ON public.approval_delegations USING btree (is_active);


--
-- Name: ix_approval_flow_nodes_flow_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_flow_nodes_flow_id ON public.approval_flow_nodes USING btree (flow_id);


--
-- Name: ix_approval_flows_business_type; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_flows_business_type ON public.approval_flows USING btree (business_type);


--
-- Name: ix_approval_flows_flow_key; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE UNIQUE INDEX ix_approval_flows_flow_key ON public.approval_flows USING btree (flow_key);


--
-- Name: ix_approval_flows_is_active; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_flows_is_active ON public.approval_flows USING btree (is_active);


--
-- Name: ix_approval_records_approver_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_records_approver_id ON public.approval_records USING btree (approver_id);


--
-- Name: ix_approval_records_request_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_records_request_id ON public.approval_records USING btree (request_id);


--
-- Name: ix_approval_requests_applicant_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_requests_applicant_id ON public.approval_requests USING btree (applicant_id);


--
-- Name: ix_approval_requests_flow_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_requests_flow_id ON public.approval_requests USING btree (flow_id);


--
-- Name: ix_approval_requests_request_no; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE UNIQUE INDEX ix_approval_requests_request_no ON public.approval_requests USING btree (request_no);


--
-- Name: ix_approval_requests_status; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_approval_requests_status ON public.approval_requests USING btree (status);


--
-- Name: ix_mp_addresses_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_addresses_user_id ON public.mp_addresses USING btree (user_id);


--
-- Name: ix_mp_browse_history_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_browse_history_user_id ON public.mp_browse_history USING btree (user_id);


--
-- Name: ix_mp_carts_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_carts_user_id ON public.mp_carts USING btree (user_id);


--
-- Name: ix_mp_favorites_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_favorites_user_id ON public.mp_favorites USING btree (user_id);


--
-- Name: ix_mp_feedbacks_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_feedbacks_user_id ON public.mp_feedbacks USING btree (user_id);


--
-- Name: ix_mp_notifications_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_notifications_user_id ON public.mp_notifications USING btree (user_id);


--
-- Name: ix_mp_order_items_order_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_order_items_order_id ON public.mp_order_items USING btree (order_id);


--
-- Name: ix_mp_orders_order_no; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_orders_order_no ON public.mp_orders USING btree (order_no);


--
-- Name: ix_mp_orders_status; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_orders_status ON public.mp_orders USING btree (status);


--
-- Name: ix_mp_orders_user_id; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_mp_orders_user_id ON public.mp_orders USING btree (user_id);


--
-- Name: ix_users_wx_openid; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE UNIQUE INDEX ix_users_wx_openid ON public.users USING btree (wx_openid);


--
-- Name: ix_users_wx_unionid; Type: INDEX; Schema: public; Owner: xcagi
--

CREATE INDEX ix_users_wx_unionid ON public.users USING btree (wx_unionid);


--
-- Name: ai_conversation_sessions ai_conversation_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversation_sessions
    ADD CONSTRAINT ai_conversation_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: ai_conversations ai_conversations_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.ai_conversations
    ADD CONSTRAINT ai_conversations_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.ai_conversation_sessions(session_id) ON DELETE CASCADE;


--
-- Name: approval_delegations approval_delegations_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_delegations
    ADD CONSTRAINT approval_delegations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: approval_delegations approval_delegations_delegate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_delegations
    ADD CONSTRAINT approval_delegations_delegate_id_fkey FOREIGN KEY (delegate_id) REFERENCES public.users(id);


--
-- Name: approval_delegations approval_delegations_delegator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_delegations
    ADD CONSTRAINT approval_delegations_delegator_id_fkey FOREIGN KEY (delegator_id) REFERENCES public.users(id);


--
-- Name: approval_flow_nodes approval_flow_nodes_flow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flow_nodes
    ADD CONSTRAINT approval_flow_nodes_flow_id_fkey FOREIGN KEY (flow_id) REFERENCES public.approval_flows(id) ON DELETE CASCADE;


--
-- Name: approval_flows approval_flows_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_flows
    ADD CONSTRAINT approval_flows_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: approval_records approval_records_approver_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_approver_id_fkey FOREIGN KEY (approver_id) REFERENCES public.users(id);


--
-- Name: approval_records approval_records_delegate_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_delegate_user_fkey FOREIGN KEY (delegate_user) REFERENCES public.users(id);


--
-- Name: approval_records approval_records_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.approval_flow_nodes(id);


--
-- Name: approval_records approval_records_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.approval_requests(id) ON DELETE CASCADE;


--
-- Name: approval_records approval_records_transferred_from_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_transferred_from_fkey FOREIGN KEY (transferred_from) REFERENCES public.users(id);


--
-- Name: approval_records approval_records_transferred_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_transferred_to_fkey FOREIGN KEY (transferred_to) REFERENCES public.users(id);


--
-- Name: approval_requests approval_requests_applicant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_applicant_id_fkey FOREIGN KEY (applicant_id) REFERENCES public.users(id);


--
-- Name: approval_requests approval_requests_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: approval_requests approval_requests_current_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_current_node_id_fkey FOREIGN KEY (current_node_id) REFERENCES public.approval_flow_nodes(id);


--
-- Name: approval_requests approval_requests_flow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_flow_id_fkey FOREIGN KEY (flow_id) REFERENCES public.approval_flows(id);


--
-- Name: excel_vector_chunks excel_vector_chunks_index_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.excel_vector_chunks
    ADD CONSTRAINT excel_vector_chunks_index_id_fkey FOREIGN KEY (index_id) REFERENCES public.excel_vector_indexes(index_id) ON DELETE CASCADE;


--
-- Name: inventory_ledger inventory_ledger_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_ledger
    ADD CONSTRAINT inventory_ledger_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.storage_locations(id);


--
-- Name: inventory_ledger inventory_ledger_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_ledger
    ADD CONSTRAINT inventory_ledger_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: inventory_ledger inventory_ledger_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_ledger
    ADD CONSTRAINT inventory_ledger_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: inventory_transactions inventory_transactions_ledger_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_ledger_id_fkey FOREIGN KEY (ledger_id) REFERENCES public.inventory_ledger(id);


--
-- Name: inventory_transactions inventory_transactions_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.storage_locations(id);


--
-- Name: inventory_transactions inventory_transactions_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: inventory_transactions inventory_transactions_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: mp_addresses mp_addresses_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_addresses
    ADD CONSTRAINT mp_addresses_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_browse_history mp_browse_history_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_browse_history
    ADD CONSTRAINT mp_browse_history_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE;


--
-- Name: mp_browse_history mp_browse_history_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_browse_history
    ADD CONSTRAINT mp_browse_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_carts mp_carts_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_carts
    ADD CONSTRAINT mp_carts_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE;


--
-- Name: mp_carts mp_carts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_carts
    ADD CONSTRAINT mp_carts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_favorites mp_favorites_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_favorites
    ADD CONSTRAINT mp_favorites_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE;


--
-- Name: mp_favorites mp_favorites_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_favorites
    ADD CONSTRAINT mp_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_feedbacks mp_feedbacks_replied_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_feedbacks
    ADD CONSTRAINT mp_feedbacks_replied_by_fkey FOREIGN KEY (replied_by) REFERENCES public.users(id);


--
-- Name: mp_feedbacks mp_feedbacks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_feedbacks
    ADD CONSTRAINT mp_feedbacks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_notifications mp_notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_notifications
    ADD CONSTRAINT mp_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mp_order_items mp_order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_order_items
    ADD CONSTRAINT mp_order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.mp_orders(id) ON DELETE CASCADE;


--
-- Name: mp_order_items mp_order_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_order_items
    ADD CONSTRAINT mp_order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE;


--
-- Name: mp_orders mp_orders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.mp_orders
    ADD CONSTRAINT mp_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: purchase_inbound_items purchase_inbound_items_inbound_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items
    ADD CONSTRAINT purchase_inbound_items_inbound_id_fkey FOREIGN KEY (inbound_id) REFERENCES public.purchase_inbounds(id);


--
-- Name: purchase_inbound_items purchase_inbound_items_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items
    ADD CONSTRAINT purchase_inbound_items_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.storage_locations(id);


--
-- Name: purchase_inbound_items purchase_inbound_items_order_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items
    ADD CONSTRAINT purchase_inbound_items_order_item_id_fkey FOREIGN KEY (order_item_id) REFERENCES public.purchase_order_items(id);


--
-- Name: purchase_inbound_items purchase_inbound_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbound_items
    ADD CONSTRAINT purchase_inbound_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: purchase_inbounds purchase_inbounds_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds
    ADD CONSTRAINT purchase_inbounds_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.purchase_orders(id);


--
-- Name: purchase_inbounds purchase_inbounds_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds
    ADD CONSTRAINT purchase_inbounds_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id);


--
-- Name: purchase_inbounds purchase_inbounds_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_inbounds
    ADD CONSTRAINT purchase_inbounds_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: purchase_order_items purchase_order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_order_items
    ADD CONSTRAINT purchase_order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.purchase_orders(id);


--
-- Name: purchase_order_items purchase_order_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_order_items
    ADD CONSTRAINT purchase_order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- Name: purchase_orders purchase_orders_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id);


--
-- Name: purchase_orders purchase_orders_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: role_permissions role_permissions_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: storage_locations storage_locations_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.storage_locations
    ADD CONSTRAINT storage_locations_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouses(id);


--
-- Name: template_usage_log template_usage_log_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.template_usage_log
    ADD CONSTRAINT template_usage_log_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.templates(id) ON DELETE CASCADE;


--
-- Name: users users_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: wechat_contact_context wechat_contact_context_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_contact_context
    ADD CONSTRAINT wechat_contact_context_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.wechat_contacts(id) ON DELETE CASCADE;


--
-- Name: wechat_tasks wechat_tasks_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: xcagi
--

ALTER TABLE ONLY public.wechat_tasks
    ADD CONSTRAINT wechat_tasks_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.wechat_contacts(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict gJZdtAT52GS4q5j5YhPNozqgJ2zb3BT0XJhf4ajfIntZKLjFWm9oQoPAndtCF0I

