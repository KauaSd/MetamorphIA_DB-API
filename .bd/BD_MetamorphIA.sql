-- =======================================================================
-- Script DDL de Criação do Banco de Dados: BD_MetamorphIA
-- SGBD: PostgreSQL 18+
-- Ajustado com Grupo, Planos/Limites, CPF/CNPJ, Tags/Áreas, Google Auth,
-- Isolamento de Chat por Professor, Perfil IA e Tabelas 2FA
-- =======================================================================

-- CREATE DATABASE "BD_MetamorphIA" WITH ENCODING = 'UTF8';

DROP TABLE IF EXISTS user_2fa_codes CASCADE;
DROP TABLE IF EXISTS user_2fa_methods CASCADE;
DROP TABLE IF EXISTS mensag_al CASCADE;
DROP TABLE IF EXISTS Mensagem CASCADE;
DROP TABLE IF EXISTS chat CASCADE;
DROP TABLE IF EXISTS Aluno CASCADE;
DROP TABLE IF EXISTS Turma CASCADE;
DROP TABLE IF EXISTS User_esc CASCADE;
DROP TABLE IF EXISTS User_grupo CASCADE;
DROP TABLE IF EXISTS User_cont CASCADE;
DROP TABLE IF EXISTS Nota_fiscal CASCADE;
DROP TABLE IF EXISTS Pgto CASCADE;
DROP TABLE IF EXISTS Escola CASCADE;
DROP TABLE IF EXISTS Grupo CASCADE;
DROP TABLE IF EXISTS Contrato CASCADE;
DROP TABLE IF EXISTS Usuario CASCADE;
DROP TABLE IF EXISTS Plano CASCADE;

-- =======================================================================
-- 1. TABELA: Plano
-- =======================================================================
CREATE TABLE Plano (
    id_plano SERIAL PRIMARY KEY,
    nome_plano VARCHAR(100) UNIQUE NOT NULL,
    max_escolas INT,
    max_turmas_por_escola INT,
    max_alunos_por_turma INT
);

-- =======================================================================
-- 2. TABELA: Usuario
-- =======================================================================
CREATE TABLE Usuario (
    id_usuario SERIAL PRIMARY KEY,
    nome_usuario VARCHAR(150) NOT NULL,
    email_usuario VARCHAR(150) UNIQUE,
    telefone_usuario VARCHAR(20) UNIQUE,
    senha_usuario VARCHAR(255),
    google_id VARCHAR(150) UNIQUE,
    cpf_cnpj VARCHAR(20),
    tipo_usuario VARCHAR(50) NOT NULL DEFAULT 'normal',
    tags_usuario TEXT
);

-- =======================================================================
-- 3. TABELA: Contrato
-- =======================================================================
CREATE TABLE Contrato (
    id_cont SERIAL PRIMARY KEY,
    tipo_cont VARCHAR(50) NOT NULL, -- 'cpf' ou 'cnpj'
    documento_cont VARCHAR(20),
    email_institucional VARCHAR(150),
    max_qtd_user INT NOT NULL DEFAULT 1,
    max_qtd_turmas INT,
    max_qtd_alunos INT,
    max_qtd_escolas INT,
    valor_contrato NUMERIC(10, 2),
    data_inicio DATE DEFAULT CURRENT_DATE,
    data_fim DATE DEFAULT (CURRENT_DATE + INTERVAL '30 days'),
    status_contrato VARCHAR(30) NOT NULL DEFAULT 'ativo',
    fk_Plano_id_plano INT NOT NULL,
    CONSTRAINT fk_contrato_plano 
        FOREIGN KEY (fk_Plano_id_plano) 
        REFERENCES Plano(id_plano) 
        ON UPDATE CASCADE 
        ON DELETE RESTRICT
);

-- =======================================================================
-- 4. TABELA: Grupo
-- =======================================================================
CREATE TABLE Grupo (
    id_grupo SERIAL PRIMARY KEY,
    nome_grupo VARCHAR(150) NOT NULL,
    email_institucional VARCHAR(150),
    fk_Usuario_id_usuario INT NOT NULL,
    fk_Contrato_id_cont INT,
    CONSTRAINT fk_grupo_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_grupo_contrato
        FOREIGN KEY (fk_Contrato_id_cont)
        REFERENCES Contrato(id_cont)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

-- =======================================================================
-- 5. TABELA: Escola
-- =======================================================================
CREATE TABLE Escola (
    id_escola SERIAL PRIMARY KEY,
    nome_escola VARCHAR(150) NOT NULL,
    email_institucional VARCHAR(150),
    fk_Grupo_id_grupo INT NOT NULL,
    fk_Contrato_id_cont INT,
    CONSTRAINT fk_escola_grupo
        FOREIGN KEY (fk_Grupo_id_grupo)
        REFERENCES Grupo(id_grupo)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_escola_contrato 
        FOREIGN KEY (fk_Contrato_id_cont) 
        REFERENCES Contrato(id_cont) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

-- =======================================================================
-- 6. TABELA: User_grupo (Vínculo Usuário <-> Grupo)
-- =======================================================================
CREATE TABLE User_grupo (
    id_user_grupo SERIAL PRIMARY KEY,
    fk_Usuario_id_usuario INT NOT NULL,
    fk_Grupo_id_grupo INT NOT NULL,
    papel VARCHAR(50) NOT NULL DEFAULT 'professor',
    tags_areas TEXT,
    CONSTRAINT uk_user_grupo UNIQUE (fk_Usuario_id_usuario, fk_Grupo_id_grupo),
    CONSTRAINT fk_user_grupo_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_user_grupo_grupo
        FOREIGN KEY (fk_Grupo_id_grupo)
        REFERENCES Grupo(id_grupo)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

-- =======================================================================
-- 7. TABELA: User_esc (Vínculo Usuário <-> Escola)
-- =======================================================================
CREATE TABLE User_esc (
    id_user_esc SERIAL PRIMARY KEY,
    fk_Usuario_id_usuario INT NOT NULL,
    fk_Escola_id_escola INT NOT NULL,
    papel VARCHAR(50) NOT NULL DEFAULT 'professor',
    tags_areas TEXT,
    pode_chat BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uk_user_esc UNIQUE (fk_Usuario_id_usuario, fk_Escola_id_escola),
    CONSTRAINT fk_user_esc_usuario 
        FOREIGN KEY (fk_Usuario_id_usuario) 
        REFERENCES Usuario(id_usuario) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_user_esc_escola 
        FOREIGN KEY (fk_Escola_id_escola) 
        REFERENCES Escola(id_escola) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

-- =======================================================================
-- 8. TABELA: User_cont (Vínculo Usuário <-> Contrato)
-- =======================================================================
CREATE TABLE User_cont (
    id_user_cont SERIAL PRIMARY KEY,
    fk_Usuario_id_usuario INT NOT NULL,
    fk_Contrato_id_cont INT NOT NULL,
    eh_pagador BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uk_user_cont UNIQUE (fk_Usuario_id_usuario, fk_Contrato_id_cont),
    CONSTRAINT fk_user_cont_usuario 
        FOREIGN KEY (fk_Usuario_id_usuario) 
        REFERENCES Usuario(id_usuario) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_user_cont_contrato 
        FOREIGN KEY (fk_Contrato_id_cont) 
        REFERENCES Contrato(id_cont) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

-- =======================================================================
-- 9. TABELA: Nota_fiscal
-- =======================================================================
CREATE TABLE Nota_fiscal (
    id_nota SERIAL PRIMARY KEY,
    valor_nota NUMERIC(10, 2) NOT NULL,
    data_emissao DATE NOT NULL DEFAULT CURRENT_DATE,
    fk_Contrato_id_cont INT NOT NULL,
    CONSTRAINT fk_nota_contrato 
        FOREIGN KEY (fk_Contrato_id_cont) 
        REFERENCES Contrato(id_cont) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

-- =======================================================================
-- 10. TABELA: Pgto
-- =======================================================================
CREATE TABLE Pgto (
    id_pgto SERIAL PRIMARY KEY,
    data_vencimento DATE NOT NULL,
    status_pagamento VARCHAR(50) NOT NULL DEFAULT 'Pendente',
    fk_Contrato_id_cont INT NOT NULL,
    CONSTRAINT fk_pgto_contrato 
        FOREIGN KEY (fk_Contrato_id_cont) 
        REFERENCES Contrato(id_cont) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

-- =======================================================================
-- 11. TABELA: Turma
-- =======================================================================
CREATE TABLE Turma (
    id_turma SERIAL PRIMARY KEY,
    nome_turma VARCHAR(100) NOT NULL,
    fk_Escola_id_escola INT NOT NULL,
    fk_Usuario_id_usuario INT,
    CONSTRAINT fk_turma_escola 
        FOREIGN KEY (fk_Escola_id_escola) 
        REFERENCES Escola(id_escola) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_turma_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

-- =======================================================================
-- 12. TABELA: Aluno
-- =======================================================================
CREATE TABLE Aluno (
    id_aluno SERIAL PRIMARY KEY,
    nome_aluno VARCHAR(150) NOT NULL,
    idade_aluno INT,
    desc_aluno TEXT,
    neuro_aluno VARCHAR(150) NOT NULL,
    perfil_ia TEXT,
    fk_Turma_id_turma INT NOT NULL,
    fk_Usuario_id_usuario INT,
    CONSTRAINT fk_aluno_turma 
        FOREIGN KEY (fk_Turma_id_turma) 
        REFERENCES Turma(id_turma) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_aluno_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

-- =======================================================================
-- 13. TABELA: chat (Conversas individuais por professor e aluno)
-- =======================================================================
CREATE TABLE chat (
    id_chat VARCHAR(100) PRIMARY KEY,
    nome_chat VARCHAR(100),
    fk_Aluno_id_aluno INT NOT NULL,
    fk_Usuario_id_usuario INT NOT NULL,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chat_aluno
        FOREIGN KEY (fk_Aluno_id_aluno)
        REFERENCES Aluno(id_aluno)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_chat_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

-- =======================================================================
-- 14. TABELA: Mensagem
-- =======================================================================
CREATE TABLE Mensagem (
    id_mensagem SERIAL PRIMARY KEY,
    tipo_remetente VARCHAR(50) NOT NULL DEFAULT 'user',
    texto_mensagem TEXT NOT NULL,
    anexo_mensagem TEXT,
    data_envio TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    fk_chat_id_chat VARCHAR(100) NOT NULL,
    fk_Aluno_id_aluno INT NOT NULL,
    fk_Usuario_id_usuario INT,
    CONSTRAINT fk_mensagem_chat 
        FOREIGN KEY (fk_chat_id_chat) 
        REFERENCES chat(id_chat) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_mensagem_aluno 
        FOREIGN KEY (fk_Aluno_id_aluno) 
        REFERENCES Aluno(id_aluno) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_mensagem_usuario
        FOREIGN KEY (fk_Usuario_id_usuario)
        REFERENCES Usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

-- =======================================================================
-- 15. TABELAS DE AUTENTICAÇÃO 2FA
-- =======================================================================
CREATE TABLE user_2fa_methods (
    id_methods SERIAL PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL DEFAULT 'none',
    secret VARCHAR(150),
    usa_verificacao BOOLEAN DEFAULT FALSE,
    data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    id_prof INT NOT NULL REFERENCES Usuario(id_usuario) ON DELETE CASCADE
);

CREATE TABLE user_2fa_codes (
    id_codigo SERIAL PRIMARY KEY,
    codigo VARCHAR(6),
    expira_em TIMESTAMP WITH TIME ZONE,
    tentativas INT DEFAULT 0,
    id_prof INT NOT NULL REFERENCES Usuario(id_usuario) ON DELETE CASCADE
);

-- =======================================================================
-- SEEDS INICIAIS DE PLANOS
-- =======================================================================
INSERT INTO Plano (nome_plano, max_escolas, max_turmas_por_escola, max_alunos_por_turma) VALUES
    ('basico', 3, 2, 2),
    ('pro', 10, 5, 10),
    ('pro_plus', 1, NULL, NULL),
    ('institucional', NULL, NULL, NULL)
ON CONFLICT (nome_plano) DO NOTHING;

-- =======================================================================
-- ÍNDICES PARA OTIMIZAÇÃO DE CHAVES ESTRANGEIRAS
-- =======================================================================
CREATE INDEX idx_contrato_plano ON Contrato(fk_Plano_id_plano);
CREATE INDEX idx_grupo_usuario ON Grupo(fk_Usuario_id_usuario);
CREATE INDEX idx_grupo_contrato ON Grupo(fk_Contrato_id_cont);
CREATE INDEX idx_escola_grupo ON Escola(fk_Grupo_id_grupo);
CREATE INDEX idx_escola_contrato ON Escola(fk_Contrato_id_cont);
CREATE INDEX idx_turma_escola ON Turma(fk_Escola_id_escola);
CREATE INDEX idx_user_grupo_usuario ON User_grupo(fk_Usuario_id_usuario);
CREATE INDEX idx_user_grupo_grupo ON User_grupo(fk_Grupo_id_grupo);
CREATE INDEX idx_user_esc_usuario ON User_esc(fk_Usuario_id_usuario);
CREATE INDEX idx_user_esc_escola ON User_esc(fk_Escola_id_escola);
CREATE INDEX idx_user_cont_usuario ON User_cont(fk_Usuario_id_usuario);
CREATE INDEX idx_user_cont_contrato ON User_cont(fk_Contrato_id_cont);
CREATE INDEX idx_nota_contrato ON Nota_fiscal(fk_Contrato_id_cont);
CREATE INDEX idx_pgto_contrato ON Pgto(fk_Contrato_id_cont);
CREATE INDEX idx_aluno_turma ON Aluno(fk_Turma_id_turma);
CREATE INDEX idx_chat_aluno_usuario ON chat(fk_Aluno_id_aluno, fk_Usuario_id_usuario);
CREATE INDEX idx_mensagem_chat ON Mensagem(fk_chat_id_chat);
CREATE INDEX idx_mensagem_aluno ON Mensagem(fk_Aluno_id_aluno);
