"""Serviço de armazenamento de anexos (Supabase Storage em nuvem com fallback para pasta local)."""

from __future__ import annotations

import base64
from pathlib import Path
import re
from typing import Any, Optional
import uuid

from config.settings import settings
from database import ArquivoAnexo, Session, Usuario, select
from fastapi import HTTPException, status
import httpx


MAX_ANEXO_BYTES = 10 * 1024 * 1024  # 10 MB por arquivo


def _sanitizar_nome_arquivo(nome: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9._-]", "_", (nome or "arquivo").strip())
    return limpo[:120] or "arquivo"


def _decodificar_data_url(conteudo: str) -> bytes:
    if not conteudo:
        return b""
    limpo = conteudo.strip()
    if "," in limpo and limpo.lower().startswith("data:"):
        limpo = limpo.split(",", 1)[1].strip()
    faltando = len(limpo) % 4
    if faltando:
        limpo += "=" * (4 - faltando)
    try:
        return base64.b64decode(limpo)
    except Exception:
        return b""


def _supabase_configurado() -> bool:
    return bool(
        getattr(settings, "SUPABASE_URL", "").strip()
        and getattr(settings, "SUPABASE_SERVICE_KEY", "").strip()
    )


def _headers_supabase(content_type: Optional[str] = None) -> dict[str, str]:
    key = settings.SUPABASE_SERVICE_KEY.strip()
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _garantir_bucket_supabase(bucket: str) -> None:
    url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/bucket"
    try:
        httpx.post(
            url,
            json={"id": bucket, "name": bucket, "public": False},
            headers=_headers_supabase("application/json"),
            timeout=15.0,
        )
    except Exception:
        pass


def _upload_supabase(object_key: str, raw_bytes: bytes, mime_type: str) -> str:
    bucket = getattr(settings, "SUPABASE_BUCKET", "metamorphia-arquivos") or "metamorphia-arquivos"
    base_url = settings.SUPABASE_URL.rstrip("/")
    url = f"{base_url}/storage/v1/object/{bucket}/{object_key}"
    headers = _headers_supabase(mime_type or "application/octet-stream")
    headers["x-upsert"] = "true"

    resp = httpx.post(url, content=raw_bytes, headers=headers, timeout=30.0)
    if resp.status_code in (400, 404) and "bucket" in (resp.text or "").lower():
        _garantir_bucket_supabase(bucket)
        resp = httpx.post(url, content=raw_bytes, headers=headers, timeout=30.0)

    if not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar arquivo para o Supabase Storage: {resp.status_code}",
        )
    return f"supabase://{bucket}/{object_key}"


def _download_supabase(caminho_supabase: str) -> bytes:
    sem_prefixo = caminho_supabase[len("supabase://") :]
    bucket, object_key = sem_prefixo.split("/", 1)
    url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    resp = httpx.get(url, headers=_headers_supabase(), timeout=30.0)
    if not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado no Supabase Storage.",
        )
    return resp.content


def _deletar_supabase(caminho_supabase: str) -> None:
    try:
        sem_prefixo = caminho_supabase[len("supabase://") :]
        bucket, object_key = sem_prefixo.split("/", 1)
        url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
        httpx.delete(url, headers=_headers_supabase(), timeout=15.0)
    except Exception:
        pass


def ler_bytes_registro_anexo(reg: ArquivoAnexo) -> bytes:
    """Lê os bytes de um ArquivoAnexo (Supabase Storage ou disco local) após validação de permissão."""
    if reg.caminho_arquivo.startswith("supabase://"):
        return _download_supabase(reg.caminho_arquivo)

    caminho = Path(reg.caminho_arquivo)
    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo físico não encontrado no armazenamento.",
        )
    return caminho.read_bytes()


def extrair_texto_docx_bytes_storage(conteudo_bytes: bytes) -> str:
    """Extrai o texto legível de um arquivo .docx salvo no storage com proteção contra Zip/XML Bomb."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns = {"w": w_ns}
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo_bytes), "r") as zin:
            infos = zin.infolist()
            if len(infos) > 200 or sum(i.file_size for i in infos) > 25 * 1024 * 1024:
                return ""
            if "word/document.xml" not in zin.namelist():
                return ""
            xml_bytes = zin.read("word/document.xml")
        cabecalho_xml = xml_bytes[:4096].upper()
        if b"<!ENTITY" in cabecalho_xml or b"<!DOCTYPE" in cabecalho_xml:
            return ""
        tree = ET.fromstring(xml_bytes)
        paragrafos: list[str] = []
        for p in tree.findall(".//w:p", ns):
            texto_p = "".join(t.text for t in p.findall(".//w:t", ns) if t.text).strip()
            if texto_p:
                paragrafos.append(texto_p)
        return "\n".join(paragrafos)
    except Exception:
        return ""


def salvar_arquivo_anexo(
    sessao: Session,
    id_prof: int,
    id_aluno: Optional[int],
    id_conversa: Optional[str],
    nome_arquivo: str,
    mime_type: str,
    data_url_ou_b64: Optional[str],
    file_id_override: Optional[str] = None,
    download_url_override: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Salva os bytes no Supabase Storage (ou pasta local em dev) e registra metadados no banco."""
    if not data_url_ou_b64:
        return None
    raw_bytes = _decodificar_data_url(data_url_ou_b64)
    if not raw_bytes:
        return None
    if len(raw_bytes) > MAX_ANEXO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Arquivo excede o limite máximo permitido de 10 MB.",
        )

    file_id = file_id_override or str(uuid.uuid4())
    nome_seguro = _sanitizar_nome_arquivo(nome_arquivo)
    mime = mime_type or "application/octet-stream"

    if _supabase_configurado():
        object_key = f"usuario_{id_prof}/aluno_{id_aluno or 0}/{file_id}_{nome_seguro}"
        caminho_salvo = _upload_supabase(object_key, raw_bytes, mime)
    else:
        pasta = (
            Path(settings.STORAGE_DIR)
            / f"usuario_{id_prof}"
            / f"aluno_{id_aluno or 0}"
        )
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{file_id}_{nome_seguro}"
        destino.write_bytes(raw_bytes)
        caminho_salvo = str(destino)

    reg = ArquivoAnexo(
        id_arquivo=file_id,
        id_prof=id_prof,
        id_aluno=id_aluno,
        id_conversa=id_conversa,
        nome_arquivo=nome_arquivo or nome_seguro,
        mime_type=mime,
        tamanho_bytes=len(raw_bytes),
        caminho_arquivo=caminho_salvo,
    )
    sessao.add(reg)
    sessao.flush()

    return {
        "file_id": file_id,
        "name": reg.nome_arquivo,
        "type": reg.mime_type,
        "size": reg.tamanho_bytes,
        "download_url": download_url_override or f"/AI/arquivos/{file_id}",
    }


def obter_arquivo_anexo(
    sessao: Session,
    file_id: str,
    professor_logado: Usuario,
) -> tuple[ArquivoAnexo, bytes]:
    """Recupera o arquivo (Supabase Storage ou disco local) validando posse do professor."""
    reg = sessao.get(ArquivoAnexo, file_id)
    if not reg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado.",
        )
    if (
        getattr(professor_logado, "tipo_usuario", "normal") != "adm_sistema"
        and reg.id_prof != professor_logado.id_usuario
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar este arquivo.",
        )

    return reg, ler_bytes_registro_anexo(reg)


def _remover_registros_e_arquivos(sessao: Session, registros: list[ArquivoAnexo]) -> None:
    for reg in registros:
        if reg.caminho_arquivo.startswith("supabase://"):
            _deletar_supabase(reg.caminho_arquivo)
        else:
            try:
                caminho = Path(reg.caminho_arquivo)
                if caminho.is_file():
                    caminho.unlink()
            except Exception:
                pass
        sessao.delete(reg)


def excluir_arquivos_por_conversa(
    sessao: Session, id_conversa: str, id_prof: int
) -> None:
    registros = (
        sessao.execute(
            select(ArquivoAnexo).where(
                ArquivoAnexo.id_conversa == id_conversa,
                ArquivoAnexo.id_prof == id_prof,
            )
        )
        .scalars()
        .all()
    )
    _remover_registros_e_arquivos(sessao, registros)


def excluir_arquivos_por_professor(sessao: Session, id_prof: int) -> None:
    registros = (
        sessao.execute(
            select(ArquivoAnexo).where(ArquivoAnexo.id_prof == id_prof)
        )
        .scalars()
        .all()
    )
    _remover_registros_e_arquivos(sessao, registros)
