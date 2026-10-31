"""CLI turnkey: `nfse-nacional emitir config/cliente.json --valor 150,00 ...`.

Pensada para o contador: aponta para o config (certificado + prestador) e emite. Também
consulta a nota pela chave, cancela e baixa a caixa postal DF-e do CNPJ.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ConfigError
from .emissor import Emissor


def _cmd_emitir(args: argparse.Namespace) -> int:
    tomador = None
    if args.tomador_doc or args.tomador_nome:
        tomador = {"cpf_cnpj": args.tomador_doc, "nome": args.tomador_nome}
    try:
        emissor = Emissor(args.config, ambiente=args.ambiente)
        nota = emissor.emitir(
            valor=args.valor,          # str pt-BR ("1.262,90") — a lib converte em Decimal
            descricao=args.descricao,
            tomador=tomador,
            numero=args.numero,
            serie=args.serie,
        )
    except ConfigError as e:           # config/dados inválidos — antes de tocar o SEFIN
        print(f"❌ config inválida:\n{e}", file=sys.stderr)
        return 2

    if nota.emitida:
        marca = "(já emitida)" if nota.status == "ja_emitida" else ""
        print(f"✅ emitida {marca}— nNFSe {nota.numero_nfse} · chave {nota.chave_acesso}")
        if args.xml_out and nota.nfse_xml:
            with open(args.xml_out, "w", encoding="utf-8") as fh:
                fh.write(nota.nfse_xml)
            print("   XML:", args.xml_out)
        if args.pdf:
            print("   DANFSe:", nota.danfse(args.pdf))
        return 0
    print(f"❌ não emitida: {nota.erro_msg}", file=sys.stderr)
    return 1


def _cmd_consultar(args: argparse.Namespace) -> int:
    nota = Emissor(args.config, ambiente=args.ambiente).consultar(args.chave)
    if nota is None:
        print("❌ nenhuma NFS-e com essa chave", file=sys.stderr)
        return 1
    print(f"✅ nNFSe {nota.numero_nfse} · chave {nota.chave_acesso}")
    if args.xml_out and nota.nfse_xml:
        Path(args.xml_out).write_text(nota.nfse_xml, encoding="utf-8")
        print("   XML:", args.xml_out)
    if args.pdf:
        print("   DANFSe:", nota.danfse(args.pdf))
    return 0


def _cmd_cancelar(args: argparse.Namespace) -> int:
    try:
        r = Emissor(args.config, ambiente=args.ambiente).cancelar(
            args.chave, motivo=args.motivo, justificativa=args.justificativa, modo=args.modo)
    except ConfigError as e:
        print(f"❌ pedido inválido:\n{e}", file=sys.stderr)
        return 2
    if not r.ok:
        print(f"❌ evento recusado: {r.erro_msg}", file=sys.stderr)
        return 1
    if r.cancelada:
        print(f"✅ NFS-e cancelada · chave {r.chave_acesso}")
    else:
        print(f"⏳ análise fiscal pedida · chave {r.chave_acesso} — a nota fica EM ANÁLISE "
              "até o município deferir")
    return 0


def _cmd_dfe(args: argparse.Namespace) -> int:
    emissor = Emissor(args.config, ambiente=args.ambiente)
    r = emissor.sincronizar_dfe(args.nsu, max_paginas=args.max_paginas)
    destino = Path(args.destino) if args.destino else None
    contagem = {"emitida": 0, "recebida": 0, "evento": 0}
    for doc in r.documentos:
        tipo = doc.classificar(emissor.cfg.prestador.cnpj)
        contagem[tipo] += 1
        if destino and doc.xml:
            pasta = destino / tipo
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{doc.chave_acesso or 'nsu'}_{doc.nsu}.xml").write_text(
                doc.xml, encoding="utf-8")
    print(f"{len(r.documentos)} documento(s) — {contagem['emitida']} emitida(s), "
          f"{contagem['recebida']} recebida(s), {contagem['evento']} evento(s)")
    print(f"último NSU: {r.ultimo_nsu}  (use --nsu {r.ultimo_nsu} na próxima vez)")
    if r.tem_mais:
        print("⚠️ há mais documentos: rode de novo com o NSU acima")
    if r.parcial:
        print(f"⚠️ parou antes do fim: {r.erro}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nfse-nacional",
                                description="Emite NFS-e pela API SEFIN Nacional.")
    p.add_argument("-v", "--verbose", action="store_true", help="mostra o log do processo")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("emitir", help="emite uma NFS-e")
    e.add_argument("config", help="caminho do config/<cliente>.json")
    e.add_argument("--valor", required=True, help="valor do serviço (ex.: 150,00)")
    e.add_argument("--descricao", required=True)
    e.add_argument("--tomador-doc", dest="tomador_doc")
    e.add_argument("--tomador-nome", dest="tomador_nome")
    e.add_argument("--numero", help="nDPS (default: contador do ambiente)")
    e.add_argument("--serie", default="1")
    e.add_argument("--ambiente", choices=["homologacao", "producao"],
                   help="homologacao = TESTE (sem validade) · producao = nota real")
    e.add_argument("--pdf", help="gera o DANFSe neste caminho")
    e.add_argument("--xml-out", dest="xml_out", help="salva o XML da NFS-e neste caminho")
    e.set_defaults(func=_cmd_emitir)

    c = sub.add_parser("consultar", help="busca a NFS-e pela chave de acesso")
    c.add_argument("config")
    c.add_argument("chave", help="chave de acesso (50 posições, com ou sem 'NFS')")
    c.add_argument("--ambiente", choices=["homologacao", "producao"])
    c.add_argument("--pdf", help="gera o DANFSe neste caminho")
    c.add_argument("--xml-out", dest="xml_out", help="salva o XML da NFS-e neste caminho")
    c.set_defaults(func=_cmd_consultar)

    k = sub.add_parser("cancelar", help="cancela uma NFS-e (ou pede a análise fiscal)")
    k.add_argument("config")
    k.add_argument("chave")
    k.add_argument("--justificativa", required=True, help="15 a 200 caracteres")
    k.add_argument("--motivo", type=int, default=1, choices=[1, 2, 9],
                   help="1=Erro na Emissão (padrão) · 2=Serviço não Prestado · 9=Outros")
    k.add_argument("--modo", choices=["direto", "analise"], default="direto",
                   help="analise = municípios que não aceitam o cancelamento direto (E0823)")
    k.add_argument("--ambiente", choices=["homologacao", "producao"])
    k.set_defaults(func=_cmd_cancelar)

    d = sub.add_parser("dfe", help="baixa a caixa postal DF-e do CNPJ (emitidas, recebidas, "
                                   "eventos)")
    d.add_argument("config")
    d.add_argument("--nsu", type=int, default=0, help="último NSU já lido (0 = desde o início)")
    d.add_argument("--max-paginas", dest="max_paginas", type=int, default=20)
    d.add_argument("--destino", help="pasta onde gravar os XMLs (emitida/recebida/evento)")
    d.add_argument("--ambiente", choices=["homologacao", "producao"])
    d.set_defaults(func=_cmd_dfe)

    args = p.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    codigo: int = args.func(args)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
