--
-- PostgreSQL database dump
--

\restrict nJb0zkJ6Hqcy6dr1biIPO4i5a8bix84rfvSrPbU2IqlL7iZDeQ5cS9nE1aseMCb

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

-- Started on 2026-07-21 15:29:33

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
-- TOC entry 219 (class 1259 OID 16435)
-- Name: alunos; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alunos (
    id_aluno integer NOT NULL,
    nome_aluno text NOT NULL,
    neurodiv_aluno text NOT NULL,
    desc_aluno text,
    idade_aluno integer,
    id_prof integer,
    id_turma integer
);


ALTER TABLE public.alunos OWNER TO postgres;

--
-- TOC entry 220 (class 1259 OID 16441)
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
-- TOC entry 5051 (class 0 OID 0)
-- Dependencies: 220
-- Name: alunos_id_aluno_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.alunos_id_aluno_seq OWNED BY public.alunos.id_aluno;


--
-- TOC entry 221 (class 1259 OID 16442)
-- Name: mensag_al; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mensag_al (
    id_aluno integer,
    id_mensagem integer
);


ALTER TABLE public.mensag_al OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 16445)
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
-- TOC entry 223 (class 1259 OID 16452)
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
-- TOC entry 5052 (class 0 OID 0)
-- Dependencies: 223
-- Name: mensagens_id_mensagem_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mensagens_id_mensagem_seq OWNED BY public.mensagens.id_mensagem;


--
-- TOC entry 224 (class 1259 OID 16453)
-- Name: professores; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.professores (
    id_prof integer NOT NULL,
    nome_prof character varying(100) NOT NULL,
    senha_prof text NOT NULL,
    email_prof text,
    num_prof character varying(15)
);


ALTER TABLE public.professores OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 16461)
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
-- TOC entry 5053 (class 0 OID 0)
-- Dependencies: 225
-- Name: professores_id_prof_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.professores_id_prof_seq OWNED BY public.professores.id_prof;


--
-- TOC entry 226 (class 1259 OID 16508)
-- Name: turmas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.turmas (
    id_turma integer NOT NULL,
    nome_turma character varying(30),
    id_prof integer
);


ALTER TABLE public.turmas OWNER TO postgres;

--
-- TOC entry 4874 (class 2604 OID 16462)
-- Name: alunos id_aluno; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos ALTER COLUMN id_aluno SET DEFAULT nextval('public.alunos_id_aluno_seq'::regclass);


--
-- TOC entry 4875 (class 2604 OID 16463)
-- Name: mensagens id_mensagem; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens ALTER COLUMN id_mensagem SET DEFAULT nextval('public.mensagens_id_mensagem_seq'::regclass);


--
-- TOC entry 4877 (class 2604 OID 16464)
-- Name: professores id_prof; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.professores ALTER COLUMN id_prof SET DEFAULT nextval('public.professores_id_prof_seq'::regclass);


--
-- TOC entry 5038 (class 0 OID 16435)
-- Dependencies: 219
-- Data for Name: alunos; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alunos (id_aluno, nome_aluno, neurodiv_aluno, desc_aluno, idade_aluno, id_prof, id_turma) FROM stdin;
10	roberto	autismo	aluno focado	10	\N	\N
7	Pedro Alves	TDAH	aluno focado	6	\N	\N
8	Julia Santos	Dislexia	aluno focado	6	\N	\N
9	Lucas Ferreira	TEA	aluno focado	6	\N	\N
12	aa	tdah	oii	12	13	\N
\.


--
-- TOC entry 5040 (class 0 OID 16442)
-- Dependencies: 221
-- Data for Name: mensag_al; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mensag_al (id_aluno, id_mensagem) FROM stdin;
\.


--
-- TOC entry 5041 (class 0 OID 16445)
-- Dependencies: 222
-- Data for Name: mensagens; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mensagens (id_mensagem, id_prof, data_mensagem, anexo_mensagem) FROM stdin;
10	7	2026-04-16 23:14:00.703503	Atividade adaptada de matemática para Pedro com foco em sequências visuais.
11	8	2026-04-16 23:14:00.703503	Texto simplificado sobre o ciclo da água com imagens de apoio.
12	9	2026-04-16 23:14:00.703503	Exercício de leitura com fontes maiores e espaçamento aumentado.
\.


--
-- TOC entry 5043 (class 0 OID 16453)
-- Dependencies: 224
-- Data for Name: professores; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.professores (id_prof, nome_prof, senha_prof, email_prof, num_prof) FROM stdin;
7	Ana Lima	1234	\N	\N
8	Carlos Melo	5678	\N	\N
9	Beatriz Souza	91011	\N	\N
10	aluno	2131	\N	\N
11	cavalo	$argon2id$v=19$m=65536,t=3,p=4$6UK3I2nMNfLrjPdp5aHwJg$9Ybd6VEpwWPqtftdhvy+xGNr0GsLk2or5i5HgnvOMnM	\N	\N
12	teste	$argon2id$v=19$m=65536,t=3,p=4$0L8gOw8DVfqX2U9DVLqPng$IgfmGJt0YpQ96jp9eYblXy24yrf3OYIkMdvDGUfzGOA	\N	\N
13	cleber	$argon2id$v=19$m=65536,t=3,p=4$rO6Ojly6i2h9CzYj1VXkkw$NltdSEAcZJBVX1YCZkIUh/5E+SwWFBGuchD1Bdk+Z2I	\N	\N
\.


--
-- TOC entry 5045 (class 0 OID 16508)
-- Dependencies: 226
-- Data for Name: turmas; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.turmas (id_turma, nome_turma, id_prof) FROM stdin;
\.


--
-- TOC entry 5054 (class 0 OID 0)
-- Dependencies: 220
-- Name: alunos_id_aluno_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.alunos_id_aluno_seq', 12, true);


--
-- TOC entry 5055 (class 0 OID 0)
-- Dependencies: 223
-- Name: mensagens_id_mensagem_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.mensagens_id_mensagem_seq', 12, true);


--
-- TOC entry 5056 (class 0 OID 0)
-- Dependencies: 225
-- Name: professores_id_prof_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.professores_id_prof_seq', 13, true);


--
-- TOC entry 4879 (class 2606 OID 16466)
-- Name: alunos alunos_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos
    ADD CONSTRAINT alunos_pkey PRIMARY KEY (id_aluno);


--
-- TOC entry 4881 (class 2606 OID 16468)
-- Name: mensagens mensagens_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens
    ADD CONSTRAINT mensagens_pkey PRIMARY KEY (id_mensagem);


--
-- TOC entry 4883 (class 2606 OID 16470)
-- Name: professores professores_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.professores
    ADD CONSTRAINT professores_pkey PRIMARY KEY (id_prof);


--
-- TOC entry 4885 (class 2606 OID 16513)
-- Name: turmas turmas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turmas
    ADD CONSTRAINT turmas_pkey PRIMARY KEY (id_turma);


--
-- TOC entry 4886 (class 2606 OID 16503)
-- Name: alunos alunos_id_prof_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos
    ADD CONSTRAINT alunos_id_prof_fkey FOREIGN KEY (id_prof) REFERENCES public.professores(id_prof);


--
-- TOC entry 4890 (class 2606 OID 16519)
-- Name: turmas id_prof; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turmas
    ADD CONSTRAINT id_prof FOREIGN KEY (id_prof) REFERENCES public.professores(id_prof);


--
-- TOC entry 4887 (class 2606 OID 16514)
-- Name: alunos id_turma; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alunos
    ADD CONSTRAINT id_turma FOREIGN KEY (id_turma) REFERENCES public.turmas(id_turma);


--
-- TOC entry 4888 (class 2606 OID 16471)
-- Name: mensag_al mensag_al_id_aluno_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensag_al
    ADD CONSTRAINT mensag_al_id_aluno_fkey FOREIGN KEY (id_aluno) REFERENCES public.alunos(id_aluno);


--
-- TOC entry 4889 (class 2606 OID 16476)
-- Name: mensagens mensagens_id_prof_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mensagens
    ADD CONSTRAINT mensagens_id_prof_fkey FOREIGN KEY (id_prof) REFERENCES public.professores(id_prof);


-- Completed on 2026-07-21 15:29:33

--
-- PostgreSQL database dump complete
--

\unrestrict nJb0zkJ6Hqcy6dr1biIPO4i5a8bix84rfvSrPbU2IqlL7iZDeQ5cS9nE1aseMCb

