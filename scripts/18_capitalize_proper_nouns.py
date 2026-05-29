#!/usr/bin/env python3
"""Stage 18 — capitalize proper nouns and acronyms inside item titles.

Web imports routinely lowercase named entities — ``markov``, ``schrodinger``,
``nmr``, ``qed``, ``bcs`` — even though they're proper nouns (people, places,
or established acronyms). The title field in Zotero is the source of truth:
once it's correctly capitalized, BetterBibTeX brace-protects each token on
export so the ``.bst`` doesn't lowercase it back.

This stage scans every item's ``title`` against a curated list of physics /
math / CS proper nouns and acronyms, applying canonical capitalization (and
diacritic restoration where it applies: ``schrodinger`` → ``Schrödinger``,
``godel`` → ``Gödel``, ``mobius`` → ``Möbius``).

Word-boundary matching only; case-insensitive lookup, but the replacement
forces the canonical form. Idempotent: running twice is a no-op the second
time.

**Conservative by design** — common-English-word names (Bell, Berry, Brown,
Hall, Born, Green, Wood …) are NOT in the list because the false-positive
risk ("bell-shaped", "brown noise") would damage legitimate titles. If you
need to capitalize one of those, do it by hand or add it to ``PROPER_NOUNS``
after auditing your titles for collisions.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    compile_canonical_replacer,
    fetch_items,
    get_client,
)

# Canonical proper nouns and acronyms. Keys are lowercase (or the
# diacritic-stripped lowercase form when the canonical contains a diacritic);
# values are the canonical capitalization to enforce.
# Hyphenated multi-token names get their own entry so they match as one unit.
PROPER_NOUNS: dict[str, str] = {
    # --- people (singular + common adjective form) ---
    "abel": "Abel", "abelian": "Abelian",
    "abrikosov": "Abrikosov",
    "anderson": "Anderson",
    "atiyah": "Atiyah",
    "banach": "Banach",
    "bardeen": "Bardeen",
    "bayes": "Bayes", "bayesian": "Bayesian",
    "berezinskii": "Berezinskii",
    "bessel": "Bessel",
    "bethe": "Bethe",
    "bloch": "Bloch",
    "bogoliubov": "Bogoliubov", "bogolyubov": "Bogoliubov",
    "boltzmann": "Boltzmann",
    "bose": "Bose",
    "brownian": "Brownian",
    "carnot": "Carnot",
    "cartan": "Cartan",
    "cauchy": "Cauchy",
    "chebyshev": "Chebyshev",
    "clifford": "Clifford",
    "coulomb": "Coulomb",
    "crooks": "Crooks",
    "de bruijn": "de Bruijn",
    "dewitt": "DeWitt",
    "dirac": "Dirac",
    "doob": "Doob",
    "doppler": "Doppler",
    "drude": "Drude",
    "einstein": "Einstein",
    "euler": "Euler", "eulerian": "Eulerian",
    "faraday": "Faraday",
    "fermat": "Fermat",
    "fermi": "Fermi",
    "feynman": "Feynman",
    "fokker": "Fokker",
    "fourier": "Fourier",
    "frobenius": "Frobenius",
    "galilean": "Galilean",
    "galois": "Galois",
    "gauss": "Gauss", "gaussian": "Gaussian",
    "gibbs": "Gibbs",
    "godel": "Gödel", "gödel": "Gödel",
    "goldstone": "Goldstone",
    "grassmann": "Grassmann",
    "hadamard": "Hadamard",
    "hamiltonian": "Hamiltonian",
    "hartree": "Hartree",
    "hawking": "Hawking",
    "heisenberg": "Heisenberg",
    "helmholtz": "Helmholtz",
    "hermitian": "Hermitian",
    "hessenberg": "Hessenberg",
    "hessian": "Hessian",
    "higgs": "Higgs",
    "hilbert": "Hilbert",
    "hofstadter": "Hofstadter",
    "holstein": "Holstein",
    "hopf": "Hopf",
    "hubbard": "Hubbard",
    "ising": "Ising",
    "ito": "Itô", "itô": "Itô",
    "jacobi": "Jacobi", "jacobian": "Jacobian",
    "jarzynski": "Jarzynski",
    "jaynes": "Jaynes",
    "kalman": "Kalman",
    "kepler": "Kepler",
    "kondo": "Kondo",
    "kraus": "Kraus",
    "krylov": "Krylov",
    "kubo": "Kubo",
    "kuramoto": "Kuramoto",
    "kähler": "Kähler", "kahler": "Kähler",
    "lagrangian": "Lagrangian",
    "lanczos": "Lanczos",
    "landau": "Landau",
    "langevin": "Langevin",
    "laplace": "Laplace",
    "lebesgue": "Lebesgue",
    "levenshtein": "Levenshtein",
    "levy": "Lévy", "lévy": "Lévy",
    "lieb": "Lieb",
    "lindblad": "Lindblad", "lindbladian": "Lindbladian",
    "lipkin": "Lipkin",
    "liouville": "Liouville",
    "lipschitz": "Lipschitz",
    "lorentz": "Lorentz",
    "lorenz": "Lorenz",
    "loschmidt": "Loschmidt",
    "lyapunov": "Lyapunov",
    "majorana": "Majorana",
    "markov": "Markov", "markovian": "Markovian",
    "maxwell": "Maxwell", "maxwellian": "Maxwellian",
    "mermin": "Mermin",
    "metropolis": "Metropolis",
    "minkowski": "Minkowski",
    "mobius": "Möbius", "möbius": "Möbius",
    "monte carlo": "Monte Carlo",
    "mott": "Mott",
    "nernst": "Nernst",
    "newton": "Newton", "newtonian": "Newtonian",
    "noether": "Noether",
    "onsager": "Onsager",
    "pauli": "Pauli",
    "peierls": "Peierls",
    "penrose": "Penrose",
    "perron": "Perron",
    "pfaffian": "Pfaffian",
    "planck": "Planck",
    "poincaré": "Poincaré", "poincare": "Poincaré",
    "poisson": "Poisson",
    "polyakov": "Polyakov",
    "pomeranchuk": "Pomeranchuk",
    "rabi": "Rabi",
    "rényi": "Rényi", "renyi": "Rényi",
    "riemann": "Riemann", "riemannian": "Riemannian",
    "rydberg": "Rydberg",
    "sachdev": "Sachdev",
    "schmidt": "Schmidt",
    "schur": "Schur",
    "schwarzschild": "Schwarzschild",
    "schrödinger": "Schrödinger", "schrodinger": "Schrödinger",
    "shannon": "Shannon",
    "shor": "Shor",
    "slater": "Slater",
    "sommerfeld": "Sommerfeld",
    "stieltjes": "Stieltjes",
    "stinespring": "Stinespring",
    "stirling": "Stirling",
    "stokes": "Stokes",
    "thomson": "Thomson",
    "thouless": "Thouless",
    "toeplitz": "Toeplitz",
    "turing": "Turing",
    "vandermonde": "Vandermonde",
    "wegner": "Wegner",
    "weierstrass": "Weierstrass",
    "wightman": "Wightman",
    "wiener": "Wiener",
    "wigner": "Wigner",
    "yukawa": "Yukawa",
    "zeeman": "Zeeman",
    "zener": "Zener",
    "zwanzig": "Zwanzig",
    # --- hyphenated / multi-word compounds ---
    "atiyah-singer": "Atiyah-Singer",
    "bacon-shor": "Bacon-Shor",
    "bardeen-cooper-schrieffer": "Bardeen-Cooper-Schrieffer",
    "berezinskii-kosterlitz-thouless": "Berezinskii-Kosterlitz-Thouless",
    "bose-einstein": "Bose-Einstein",
    "bose-hubbard": "Bose-Hubbard",
    "de broglie": "de Broglie",
    "fermi-dirac": "Fermi-Dirac",
    "fokker-planck": "Fokker-Planck",
    "hartree-fock": "Hartree-Fock",
    "jaynes-cummings": "Jaynes-Cummings",
    "kibble-zurek": "Kibble-Zurek",
    "klein-gordon": "Klein-Gordon",
    "kosterlitz-thouless": "Kosterlitz-Thouless",
    "kuramoto-sivashinsky": "Kuramoto-Sivashinsky",
    "lieb-robinson": "Lieb-Robinson",
    "lipkin-meshkov-glick": "Lipkin-Meshkov-Glick",
    "mermin-wagner": "Mermin-Wagner",
    "perron-frobenius": "Perron-Frobenius",
    "sachdev-ye-kitaev": "Sachdev-Ye-Kitaev",
    "stern-gerlach": "Stern-Gerlach",
    "sturm-liouville": "Sturm-Liouville",
    "suzuki-trotter": "Suzuki-Trotter",
    "van der waals": "van der Waals",
    "wiener-khinchin": "Wiener-Khinchin",
    "yang-baxter": "Yang-Baxter",
    "yang-mills": "Yang-Mills",
    # --- acronyms (3+ chars to keep false-positive risk low) ---
    "aklt": "AKLT",
    "bcs": "BCS",
    "bec": "BEC",
    "bkt": "BKT",
    "cnn": "CNN",
    "dft": "DFT",
    "dmft": "DMFT",
    "dmrg": "DMRG",
    "ebm": "EBM",
    "epr": "EPR",
    "esr": "ESR",
    "eth": "ETH",
    "fft": "FFT",
    "gan": "GAN",
    "gflownet": "GFlowNet",
    "kpz": "KPZ",
    "ldpc": "LDPC",
    "llm": "LLM",
    "lstm": "LSTM",
    "mbl": "MBL",
    "mera": "MERA",
    "mhd": "MHD",
    "mlp": "MLP",
    "mps": "MPS",
    "mri": "MRI",
    "nlp": "NLP",
    "nmr": "NMR",
    "otoc": "OTOC",
    "pde": "PDE",
    "peps": "PEPS",
    "qaoa": "QAOA",
    "qcd": "QCD",
    "qec": "QEC",
    "qed": "QED",
    "qft": "QFT",
    "qkd": "QKD",
    "qpt": "QPT",
    "rbm": "RBM",
    "rnn": "RNN",
    "sde": "SDE",
    "syk": "SYK",
    "tebd": "TEBD",
    "vae": "VAE",
    "vit": "ViT",
    "vqe": "VQE",
    "xxz": "XXZ",
}

# The factory pre-compiles a single alternation regex (longest keys first, so
# ``bose-einstein`` matches before bare ``bose``) and returns an idempotent
# replace function — see ``compile_canonical_replacer`` in zotcleanup.helpers.
_capitalize = compile_canonical_replacer(PROPER_NOUNS)


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("title") or ""
    if title:
        ch.set("title", _capitalize(title))
    return ch


def _is_candidate(item) -> bool:
    # Cheap pre-filter: just probe the alternation regex, don't run the full
    # substitution. `_capitalize.pattern` is the compiled alternation
    # ``compile_canonical_replacer`` attached to the returned function.
    title = item["data"].get("title") or ""
    return bool(title) and _capitalize.pattern.search(title) is not None


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    items = fetch_items(zot, None)
    cand = [it for it in items if _is_candidate(it)]
    apply_updates(
        zot,
        cand,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="items",
    )


if __name__ == "__main__":
    main()
