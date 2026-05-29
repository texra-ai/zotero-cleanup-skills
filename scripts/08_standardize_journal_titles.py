#!/usr/bin/env python3
"""Stage 08 — standardize journal titles and abbreviations.

Ported from ``pyzotero_abbreviations_clean.ipynb`` (the ``update_journal`` helper
plus its ~45-entry table). For each journal article whose ``publicationTitle``
exactly matches a known variant, set the canonical title and abbreviation.

Cosmetic and order-independent; conventionally run last. Edit ``JOURNAL_TABLE``
to add your own journals.
"""

from __future__ import annotations

from zotcleanup import Changes, apply_updates, build_parser, fetch_items, get_client

# (publicationTitle as found)  ->  (canonical publicationTitle, journalAbbreviation)
JOURNAL_TABLE: dict[str, tuple[str, str]] = {
    "Phys. Rev. Lett.": ("Physical Review Letters", "Phys. Rev. Lett."),
    "Phys. Rev. A": ("Physical Review A", "Phys. Rev. A"),
    "Phys. Rev. B": ("Physical Review B", "Phys. Rev. B"),
    "Phys. Rev. D": ("Physical Review D", "Phys. Rev. D"),
    "Phys. Rev. E": ("Physical Review E", "Phys. Rev. E"),
    "Phys. Rev. X": ("Physical Review X", "Phys. Rev. X"),
    "Phys. Rev. Research": ("Physical Review Research", "Phys. Rev. Research"),
    "Phys. Rev. Applied": ("Physical Review Applied", "Phys. Rev. Applied"),
    "Rev. Mod. Phys.": ("Reviews of Modern Physics", "Rev. Mod. Phys."),
    "npj Quantum Information": ("npj Quantum Information", "NPJ Quantum Inf."),
    "Communications in Mathematical Physics": (
        "Communications in Mathematical Physics", "Commun. Math. Phys."),
    "IEEE Transactions on Information Theory": (
        "IEEE Transactions on Information Theory", "IEEE Trans. Inf. Theory"),
    "Journal of Mathematical Physics": ("Journal of Mathematical Physics", "J. Math. Phys."),
    "J. Math. Phys.": ("Journal of Mathematical Physics", "J. Math. Phys."),
    "Journal of Statistical Mechanics: Theory and Experiment": (
        "Journal of Statistical Mechanics: Theory and Experiment", "J. Stat. Mech.: Theory Exp."),
    "Journal of Physics A: Mathematical and General": (
        "Journal of Physics A: Mathematical and General", "J. Phys. A"),
    "Journal of Physics A: Mathematical and Theoretical": (
        "Journal of Physics A: Mathematical and Theoretical", "J. Phys. A"),
    "Journal of Physics B: Atomic, Molecular and Optical Physics": (
        "Journal of Physics B: Atomic, Molecular and Optical Physics", "J. Phys. B"),
    "Journal of Physics: Condensed Matter": (
        "Journal of Physics: Condensed Matter", "J. Phys. Condens. Matter"),
    "Journal of Physics: Conference Series": (
        "Journal of Physics: Conference Series", "J. Phys. Conf. Ser."),
    "SciPost Physics": ("SciPost Physics", "SciPost Phys."),
    "Quantum Science and Technology": ("Quantum Science and Technology", "Quantum Sci. Technol."),
    "Quantum Information and Computation": (
        "Quantum Information and Computation", "Quantum Inf. Comput."),
    "Journal of High Energy Physics": ("Journal of High Energy Physics", "J. High Energy Phys."),
    "Physics Letters A": ("Physics Letters A", "Phys. Lett. A"),
    "Physics Today": ("Physics Today", "Phys. Today"),
    "Reports on Progress in Physics": ("Reports on Progress in Physics", "Rep. Prog. Phys."),
    "Proceedings of the Royal Society A: Mathematical, Physical and Engineering Sciences": (
        "Proceedings of the Royal Society A", "Proc. R. Soc. A"),
    "Proceedings of the National Academy of Sciences of the United States of America": (
        "Proceedings of the National Academy of Sciences", "Proc. Natl. Acad. Sci."),
    "SIAM Journal on Computing": ("SIAM Journal on Computing", "SIAM J. Comput."),
    "Annals of Statistics": ("Annals of Statistics", "Ann. Stat."),
    "Annals of Physics": ("Annals of Physics", "Ann. Phys."),
    "SIAM Review": ("SIAM Review", "SIAM Rev."),
    "Journal of Machine Learning Research": (
        "Journal of Machine Learning Research", "J. Mach. Learn. Res."),
    "Nature Communications": ("Nature Communications", "Nat. Commun."),
    "Nature communications": ("Nature Communications", "Nat. Commun."),
    "Nature Reviews Physics": ("Nature Reviews Physics", "Nat. Rev. Phys."),
    "Nat Rev Phys": ("Nature Reviews Physics", "Nat. Rev. Phys."),
    "Nature Physics": ("Nature Physics", "Nat. Phys."),
    "Nature physics": ("Nature Physics", "Nat. Phys."),
    "Nature Photonics": ("Nature Photonics", "Nat. Photonics"),
    "Nature photonics": ("Nature Photonics", "Nat. Photonics"),
    "The Journal of Chemical Physics": ("The Journal of Chemical Physics", "J. Chem. Phys."),
    "Journal of Statistical Physics": ("Journal of Statistical Physics", "J. Stat. Phys."),
    "Advances in Mathematics": ("Advances in Mathematics", "Adv. in. Math."),
    "Annual Review of Condensed Matter Physics": (
        "Annual Review of Condensed Matter Physics", "Annu. Rev. Condens. Matter Phys."),
    "Phys. Rev.": ("Physical Review", "Phys. Rev."),
    "Physical Review": ("Physical Review", "Phys. Rev."),
    # Full-title keys: fix the abbreviation when the title is already canonical.
    "Physical Review Letters": ("Physical Review Letters", "Phys. Rev. Lett."),
    "Physical Review A": ("Physical Review A", "Phys. Rev. A"),
    "Physical Review B": ("Physical Review B", "Phys. Rev. B"),
    "Physical Review D": ("Physical Review D", "Phys. Rev. D"),
    "Physical Review E": ("Physical Review E", "Phys. Rev. E"),
    "Physical Review X": ("Physical Review X", "Phys. Rev. X"),
    "Physical Review Research": ("Physical Review Research", "Phys. Rev. Research"),
    "Physical Review Applied": ("Physical Review Applied", "Phys. Rev. Applied"),
    # Additional journals and spelling variants from the earlier abbreviations notebook.
    "Review of Modern Physics": ("Reviews of Modern Physics", "Rev. Mod. Phys."),
    "Scientific Reports": ("Scientific Reports", "Sci. Rep."),
    "Science Bulletin": ("Science Bulletin", "Sci. Bull."),
    "SciPost Phys": ("SciPost Physics", "SciPost Phys."),
}


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    found = data.get("publicationTitle")
    if found in JOURNAL_TABLE:
        title, abbreviation = JOURNAL_TABLE[found]
        ch.set("publicationTitle", title)
        ch.set("journalAbbreviation", abbreviation)
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()

    items = fetch_items(zot, "journalArticle")
    candidates = [it for it in items if it["data"].get("publicationTitle") in JOURNAL_TABLE]

    apply_updates(
        zot,
        candidates,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="journal articles",
    )


if __name__ == "__main__":
    main()
