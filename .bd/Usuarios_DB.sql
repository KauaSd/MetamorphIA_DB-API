--
-- PostgreSQL database dump
--

\restrict 1QraakeOhd6QEb2MSrJtz2mtNfnjCC7q43prwuFjJjR1tojl2yJELac7qQ357dF

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

-- Started on 2026-05-01 22:47:47

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 220 (class 1259 OID 16398)
-- Name: alunos; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alunos (
    id_aluno integer NOT NULL,
    nome_aluno character varying(100) NOT NULL,
    neurodiv_aluno character varying(80) NOT NULL
);


ALTER TABLE public.alunos OWNER TO postgres;

--
-- TOC entry 219 (class 1259 OID 16397)
-- Name: alunos_id_aluno_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.alunos_id_aluno_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alunos_id_aluno_seq OWNER TO postgres;

--
-- TOC entry 5041 (class 0 OID 0)
-- Dependencies: 219
-- Name: alunos_id_aluno_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.alunos_id_aluno_seq OWNED BY public.alunos.id_aluno;


--
-- TOC entry 221 (class 1259 OID 16418)
-- Name: mensag_al; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mensag_al (
    id_aluno integer,
    id_mensagem integer
);


ALTER TABLE public.mensag_al OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 16460)
-- Name: mensagens; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mensagens (
    id_mensagem integer NOT NULL,
    id_prof integer,
    data_mensagem timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    anexo_mensagem text
);


ALTER TABLE public.mensagens OWNER TO postgres;

--
-- TOC entry 224 (class 1259 OID 16459)
-- Name: mensagens_id_mensagem_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mensagens_id_mensagem_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mensagens_id_mensagem_seq OWNER TO postgres;

--
-- TOC entry 5042 (class 0 OID 0)
-- Dependencies: 224
-- Name: mensagens_id_mensagem_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mensagens_id_mensagem_seq OWNED BY public.mensagens.id_mensagem;


--
-- TOC entry 223 (class 1259 OID 16432)
-- Name: professores; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.professores (
    id_prof integer NOT NULL,
    nome_prof character varying(100) NOT NULL,
    senha_prof text NOT NULL
);


ALTER TABLE public.professores OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 16431)
-- Name: professores_id_prof_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.professores_id_prof_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.professores_id_prof_seq OWNER TO postgres;

--
-- TOC entry 5043 (class 0 OID 0)
-- Dependencies: 222
-- Name: professores_id_prof_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.professores_id_prof_seq OWNED BY public.professores.id_prof;


--
-- TOC entry 4870 (class 2604 OID 16401)
-- Name: alunos id_aluno; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos ALTER COLUMN id_aluno SET DEFAULT nextval('public.alunos_id_aluno_seq'::regclass);


--
-- TOC entry 4872 (class 2604 OID 16463)
-- Name: mensagens id_mensagem; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens ALTER COLUMN id_mensagem SET DEFAULT nextval('public.mensagens_id_mensagem_seq'::regclass);


--
-- TOC entry 4871 (class 2604 OID 16435)
-- Name: professores id_prof; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.professores ALTER COLUMN id_prof SET DEFAULT nextval('public.professores_id_prof_seq'::regclass);


--
-- TOC entry 5030 (class 0 OID 16398)
-- Dependencies: 220
-- Data for Name: alunos; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alunos (id_aluno, nome_aluno, neurodiv_aluno) FROM stdin;
7	Pedro Alves	TDAH
8	Julia Santos	Dislexia
9	Lucas Ferreira	TEA
\.


--
-- TOC entry 5031 (class 0 OID 16418)
-- Dependencies: 221
-- Data for Name: mensag_al; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mensag_al (id_aluno, id_mensagem) FROM stdin;
\.


--
-- TOC entry 5035 (class 0 OID 16460)
-- Dependencies: 225
-- Data for Name: mensagens; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mensagens (id_mensagem, id_prof, data_mensagem, anexo_mensagem) FROM stdin;
10	7	2026-04-16 23:14:00.703503	Atividade adaptada de matemática para Pedro com foco em sequências visuais.
11	8	2026-04-16 23:14:00.703503	Texto simplificado sobre o ciclo da água com imagens de apoio.
12	9	2026-04-16 23:14:00.703503	Exercício de leitura com fontes maiores e espaçamento aumentado.
\.


--
-- TOC entry 5033 (class 0 OID 16432)
-- Dependencies: 223
-- Data for Name: professores; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.professores (id_prof, nome_prof, senha_prof) FROM stdin;
7	Ana Lima	1234
8	Carlos Melo	5678
9	Beatriz Souza	91011
\.


--
-- TOC entry 5044 (class 0 OID 0)
-- Dependencies: 219
-- Name: alunos_id_aluno_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.alunos_id_aluno_seq', 9, true);


--
-- TOC entry 5045 (class 0 OID 0)
-- Dependencies: 224
-- Name: mensagens_id_mensagem_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.mensagens_id_mensagem_seq', 12, true);


--
-- TOC entry 5046 (class 0 OID 0)
-- Dependencies: 222
-- Name: professores_id_prof_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.professores_id_prof_seq', 9, true);


--
-- TOC entry 4875 (class 2606 OID 16406)
-- Name: alunos alunos_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos
    ADD CONSTRAINT alunos_pkey PRIMARY KEY (id_aluno);


--
-- TOC entry 4879 (class 2606 OID 16469)
-- Name: mensagens mensagens_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens
    ADD CONSTRAINT mensagens_pkey PRIMARY KEY (id_mensagem);


--
-- TOC entry 4877 (class 2606 OID 16442)
-- Name: professores professores_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.professores
    ADD CONSTRAINT professores_pkey PRIMARY KEY (id_prof);


--
-- TOC entry 4880 (class 2606 OID 16421)
-- Name: mensag_al mensag_al_id_aluno_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensag_al
    ADD CONSTRAINT mensag_al_id_aluno_fkey FOREIGN KEY (id_aluno) REFERENCES public.alunos(id_aluno);


--
-- TOC entry 4881 (class 2606 OID 16470)
-- Name: mensagens mensagens_id_prof_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens
    ADD CONSTRAINT mensagens_id_prof_fkey FOREIGN KEY (id_prof) REFERENCES public.professores(id_prof);


-- Completed on 2026-05-01 22:47:47

--
-- PostgreSQL database dump complete
--

\unrestrict 1QraakeOhd6QEb2MSrJtz2mtNfnjCC7q43prwuFjJjR1tojl2yJELac7qQ357dF

