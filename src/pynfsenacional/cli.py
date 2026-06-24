"""CLI turnkey: `nfse-nacional emitir config/cliente.json --valor 150,00 ...`.

Pensada para o contador: aponta para o config (certificado + prestador) e emite.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError
from .emissor import Emissor


def _to_float(s: str) -> float:
    """Aceita '1.262,90', '1262.90', '100'. Padrão pt-BR."""
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _cmd_emitir(args: argparse.Namespace) -> int:
    tomador = None
    if args.tomador_doc or args.tomador_nome:
        tomador = {"cpf_cnpj": args.tomador_doc, "nome": args.tomador_nome}
    try:
        emissor = Emissor(args.config, ambiente=args.ambiente)
        nota = emissor.emitir(
            valor=_to_float(args.valor),
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

    args = p.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    codigo: int = args.func(args)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
