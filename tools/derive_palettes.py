"""Derive `src/manuscript_guard/data/palettes.json` from the collections' own files.

    python tools/derive_palettes.py <folder> [--fetch]

The palettes are other people's, and each is read from the file its collection keeps it in,
at a commit named here, with that file's SHA-256: a file that is not the one named is
refused. `--fetch` downloads each into `<folder>` first, from the address written beside
it. Nothing in the derived file is typed by hand except Okabe and Ito's eight colours, which
their page publishes as numbers and which are written here with it.

What each palette is to a reader with a colour-vision deficiency is computed from its
colours by `manuscript_guard.palettes.assess`, the rule `check` holds a figure to, so the
file says what the toolkit's own check says of each, beside what the collection claims.

Each collection's licence allows its colours to be copied with its notice, which
`src/manuscript_guard/data/palettes_LICENSES.txt` and ATTRIBUTION.md carry. The R package
takes the same file (`r/manuscriptguard/inst/extdata/palettes.json`), written here too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from manuscript_guard import palettes  # noqa: E402
from manuscript_guard.colour import hex_of, parse  # noqa: E402

OUT = REPO / "src" / "manuscript_guard" / "data" / "palettes.json"
R_OUT = REPO / "r" / "manuscriptguard" / "inst" / "extdata" / "palettes.json"
#: Each collection's licence and notice, written beside the data from the collections' own
#: files.
LICENCES_OUT = OUT.with_name("palettes_LICENSES.txt")
R_LICENCES_OUT = R_OUT.with_name("palettes_LICENSES.txt")
RAW = "https://raw.githubusercontent.com"


@dataclass(frozen=True)
class Source:
    file: str  # its name in the folder
    url: str
    sha256: str


MET = "BlakeRMills/MetBrewer/58839e5ac7c7d604c8704581f7b201a29986b814"
MOMA = "BlakeRMills/MoMAColors/854a8dae3979a01644790a7cb85d4b2554b1e63a"
NATPARKS = "kevinsblake/NatParksPalettes/215128838db62887f26cb853581a7a7edc1a1f53"
PNW = "jakelawlor/PNWColors/f16a14fcb0a1f93741e1acec221ce6391d93f0fa"
WES = "karthik/wesanderson/02e4129c185e9d3c49b05b580717f35be2eef5c3"
BREWER = "axismaps/colorbrewer/7d135fc4e19eda73f2eb1bf55fcdf4a04fe4881f"
VIRIDIS = "BIDS/colormap/bc549477db0c12b54a5928087552ad2cf274980f"
CIVIDIS = "pnnl/cmaputil/a153df50156b3a7bf93d44abae6696a7b01cd47a"
CRAMERI = "callumrollo/cmcrameri/78f02a088fa3c4fb4cb8aa92bd8e52389ab9d09a"

#: Crameri's maps, as cmcrameri keeps his version 8.0 files, one map to a file.
CRAMERI_MAPS = {
    "acton": "068da7de02af4d0607faa08b233c26065a9c582911e437bc686962ebe021ceda",
    "actonS": "b44987b0980286765542e7092751ee654b0bb6c281c816b7306415219c72caf3",
    "bam": "b45025db37b70695a5256c121965d0169bc10bd67fc921516b4b2c7e129f39e7",
    "bamO": "5cfe1d75b3aadb0f5bf18aa3198ff19d8665bb25d22f303c63228fa917050bf0",
    "bamako": "cc83bc14c03778c140d052a9b5b364fac26ffd825e390ba7676c44e2fa2c18ed",
    "bamakoS": "ebf3b29729455fc278ebe870314158a3d31b0ed5b16ad257e4643f46c27b9fd0",
    "batlow": "918dd393177e126685437f234f4c1f7c8a446437c1c68820f3bc1a8423e91bd1",
    "batlowK": "f4805caa79ec4c21a130839c0fe0089136d1bed08f6bc6bd25edf0461632f7e7",
    "batlowKS": "cc140878f9eb74921613ab2c36339d89584f1d7d363ad68bad6eafa90f974a2e",
    "batlowS": "b9e21497dfe022b3f332c78661984ce31ad66442a51c1967a04420ed6177100e",
    "batlowW": "029dd91ed9e022ac7e8fbf399d6be70755f6c0a600ee740504951d5ecd970c72",
    "batlowWS": "cdd77c5f2107461cb55b7e28fa6597334979d48d18c3f894d641a28a21f53c37",
    "berlin": "d66b056833f3f2ffed2889dc1d1143d23fc404e6c3b53299d3f939c61f557410",
    "bilbao": "b641316b9bc2a952abecdf47494ae857d85017fb3715dfba68e6836fc8c6946f",
    "bilbaoS": "e2d18e80b9a002da40a60f4bf39e3cbb4bfa0c093a1d220e762d6985817bbfe0",
    "broc": "f4404b8badae36fd33af4879e42bb27ce6c7c09496e5b85452ff6ebd2eac9f44",
    "brocO": "aaf2d6394b4e9e5921c7dbfca48e166efb8503e70c6727b73bc686ac4ad75645",
    "buda": "d83c60b09f9a58282db23e34b7177b5704e76d7968c2380ba6e146d3dc913179",
    "budaS": "714f01fe56f2e27a11ec1bf8dd41b03fd10101b3613f58c5ccca42ebd1dbf0c9",
    "bukavu": "ad2bf89f50e0cdca1a2b512cf8eac16f75ccaef91c36f0f9a8984eaee03196c3",
    "cork": "44e22ae0750cb398575980c680110569bdbc2ffd2155bd8999d6452b4c0784e0",
    "corkO": "23f53f0dfde0cec24d5307d1315d1acfb70700f24c4acfb6d2497c7a32af7992",
    "davos": "0ca57a52e94c12c05aef0abf22f363f9fed0cb831cdde2aed76ee8bb4d950bd9",
    "davosS": "66c958c9fc2335d7501f258107780475864f3f3c727cdbcdc8658ce9bfe88d9a",
    "devon": "b9573d181e49ead6e6daef40641b82b04116e2f9dacb94b4a9fdd3afc2f55dd0",
    "devonS": "1f4e7afee3d8fbcf015bf2e5805b401552e29ebcf6ec8969333f970e7ec30c0b",
    "fes": "5210ecef90ef3691f3a028a9be4b2232210b28ac97fa2a0afa3fb775b550f22d",
    "glasgow": "1fd603c787431927b006a99c8590cdaa77a285da004f017dc766b943332246ce",
    "glasgowS": "3edb4ed606dffc534ad00751229cba91d98d37717c0ded17f981c1b97719239f",
    "grayC": "180fdc4094571988ef8bbbc6f27740b94d6b1ebe06c86cea90e961cf5e1ba6e4",
    "grayCS": "fa3c1448dcb410432fd35d53dd841640584867825e285c023566415b45c0e0dc",
    "hawaii": "e5f14111f1cc67d685ae219048a816cc7ec9ab5da8171dd8d921bedabb791f9b",
    "hawaiiS": "1216f2832cac44dfa3b9a7dca083c7c944463d06fc05aa791b6481c24c7fdc8c",
    "imola": "aa0689d10ae651cf0d04c23fddf1788e7a3922a76c415414e92d3f9b160926d5",
    "imolaS": "26b5c6496e5b15976b99a185a7056238d43a684775e57f094f57b670a92c6f02",
    "lajolla": "7541ff8f5267045b8fc716c53d2fa9153882fe23471c74f8c3692ff57aef1971",
    "lajollaS": "a7db4e2e33f1dfc933d02650524ac9257ec0b72f16fac81a70c80b2d58eb3a21",
    "lapaz": "e507ceb2527a0384004d7570d4919de74f63d281dde25a7c6cf936ee47444a2c",
    "lapazS": "5de91f65c5fc80c9fc76fa76afb91a6ece8c5a9e0c9f05c2e26bee7d03fd7817",
    "lipari": "59a26ca79c66da1674f21e4ef83dd6a428c7f1e768327fc4b09e3242b7b81829",
    "lipariS": "99d86f5f42b01211c102d1088fea4abf38116701bb98629d19b6afeb446420b9",
    "lisbon": "6d12d616574f381546c2e1921264defc9f01a26d99c35da3f7aafdbc48cb335b",
    "managua": "9986430ea0fb3146d25ef5badc3d071f7113002a914e28fe8223cce7cdf868a9",
    "navia": "79c6235b421a120e24694dfac67bbbcbc21a3faed0a8a7c72ad8d3c7c41acbfb",
    "naviaS": "9391825fa99eb364e541df846c953b4857b2ae6dd310c749ee0ef2ca5260d9f9",
    "nuuk": "996ae6012b53c4e50c9a999d47bbae2d95db14501661df1ac59b2854eb6a8511",
    "nuukS": "f6cba3b563eb72fb3d7fefe1a164af4602f4ce8085b02ebe8387c9a4bd905b3e",
    "oleron": "b0e8d37fdb2ddaa4e79380c1eb82ef578365d8258d7dd597d8b58aca9f3b499a",
    "oslo": "4e29e907d1a07e05481ee6856efe4b5266d85f89eea8c82affde764aacaf1f89",
    "osloS": "b7b252a48c4035a7a13960ba811d1d8e7cc80641f28acb0c92581f1b16c3ed70",
    "roma": "3b71680d6ea001c6186569aab00e12baf0a10a5ac2e4b6305c3d8163f630b8c0",
    "romaO": "5946167e7ce80161f7f12c7ceae34730e06c42a31fa0000057b2bd785c04c74a",
    "tofino": "8eed16a2142c2280762b332512651db60bcf954fab624395ae081b64da1746f5",
    "tokyo": "e7ce268dbcd36a9cb53e587f3b31592dedb4ed6c9a4e9b09968f810375738042",
    "tokyoS": "9f40d09f431a56f0789fc4e23d4fca65e9519680d50de251f3905cc45beb0ef0",
    "turku": "49961085d0836dc7a8ca6eb78f005b05db791dc11050f565841cb535324e012d",
    "turkuS": "7bdaaa25b27e252355a4aa956a6ad5d0e52e1b92f487727c606275fe1237ec1c",
    "vanimo": "aa0d19f607b442b3532e4575e183560ac620268341ee6c079da04cca4f39819d",
    "vik": "60c2abfbffdfd9e7567cfeea1387bfe270eb036efe7262fdd7bf713058bacae2",
    "vikO": "5847a85ed6fad5ce1b23baa6b1dfc244327e4452200e725d79ce5d6f8c403b93",
}  # fmt: skip

SOURCES = {
    "met": Source(
        "metbrewer.R",
        f"{RAW}/{MET}/R/PaletteCode.R",
        "eeb6da2a7dccc8162e843867017d205b27e0c0e6725733082d1c447c5365bb73",
    ),
    "moma": Source(
        "momacolors.R",
        f"{RAW}/{MOMA}/R/Colors.R",
        "5fdd04802e9e81735b3ea3fbc6ff8e0ef53d1f68a91d4208cefcd9a3ff57eac7",
    ),
    "natparks": Source(
        "natparks.R",
        f"{RAW}/{NATPARKS}/R/NatParksPalettes.R",
        "41a59fd2cb0539bf0f19f4ea4af2f02b21b931e625f254d711e5a20f04f269ea",
    ),
    "pnw": Source(
        "pnwcolors.R",
        f"{RAW}/{PNW}/R/PNWColors.R",
        "d8661b15b85508f9042e65abf5037978cf6cb3e8b8c434666d5ec5ed6d7ed4f6",
    ),
    "wes": Source(
        "wesanderson.R",
        f"{RAW}/{WES}/R/colors.R",
        "a2e6e12e3e367396849d46f854aa743ea00df6d52ba7708bc3166d165928a373",
    ),
    "brewer": Source(
        "colorbrewer.json",
        f"{RAW}/{BREWER}/export/colorbrewer.json",
        "729cb527c1edcf3267c4521df29ede5092f3e6171c5a259e2ebdd252335840b9",
    ),
    "viridis": Source(
        "viridis.py",
        f"{RAW}/{VIRIDIS}/colormaps.py",
        "b7478d10e2ccfdb22128867e137f16f55b687e9c225065e91bcbd6bb9e6c0352",
    ),
    "cividis": Source(
        "cividis.txt",
        f"{RAW}/{CIVIDIS}/colormaps/cividis.txt",
        "6bc796b7883a014a79e27cc3545f131f1d4c21419dc5f97626da2c896b65bc36",
    ),
    **{
        f"crameri/{name}": Source(f"crameri-{name}.txt",
                                  f"{RAW}/{CRAMERI}/cmcrameri/cmaps/{name}.txt", digest)
        for name, digest in CRAMERI_MAPS.items()
    },  # fmt: skip
}

#: The file each collection states its licence in, at the commit its colours are read at, with
#: its SHA-256. MetBrewer and PNWColors state theirs in the package's DESCRIPTION alone;
#: wesanderson and NatParksPalettes give R's "MIT + file LICENSE", a year and a holder, to
#: which the MIT licence's own words are added, as MoMAColors gives them whole.
LICENCE_FILES = {
    "MetBrewer": Source("metbrewer-DESCRIPTION", f"{RAW}/{MET}/DESCRIPTION",
                        "9a74d4f3d39a8e586ed839e0d4988ed109ff1d8fe61a47b544c89e116b9eed89"),
    "MoMAColors": Source("momacolors-LICENSE.md", f"{RAW}/{MOMA}/LICENSE.md",
                         "00a4160670017835e099da08a3126b555850d6182bf48e757282ad80bc320d7b"),
    "NatParksPalettes": Source("natparks-LICENSE", f"{RAW}/{NATPARKS}/LICENSE",
                               "49a33210ab1f0964256a704b2b420d729090b6afc80f8371e519a3de92e372e7"),
    "PNWColors": Source("pnwcolors-DESCRIPTION", f"{RAW}/{PNW}/DESCRIPTION",
                        "2fa6ed95528417a964e09f45eff3ca3d84e44b67d095ea59032099f566f64228"),
    "wesanderson": Source("wesanderson-LICENSE", f"{RAW}/{WES}/LICENSE",
                          "2cb2a63bc30cf6c250f31df64a63ebf552682b91cda70b4b6bd1756b89d00088"),
    "ColorBrewer": Source("colorbrewer-LICENCE.txt", f"{RAW}/{BREWER}/LICENCE.txt",
                          "b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1"),
    "viridis": Source("viridis-LICENSE.txt", f"{RAW}/{VIRIDIS}/LICENSE.txt",
                      "30419703377136667f2c8a426d396874a8dadf53699d277fc8ad759d05092799"),
    "cividis": Source("cividis-LICENSE", f"{RAW}/{CIVIDIS}/LICENSE",
                      "3282e3c57335ff7a005ee184cfda62a9a68b9d038b66e8521e1467bffb69b2fe"),
    "Crameri": Source("crameri-LICENSE.txt", f"{RAW}/{CRAMERI}/LICENSE.txt",
                      "f8ccecbeb9687f6b09a2cb13f12521c067ccb111280d1ea632c9500131b83e3b"),
}  # fmt: skip
#: Where ColorBrewer gives the notice its licence asks to be kept: the head of its schemes.
BREWER_NOTICE = Source(
    "colorbrewer-schemes.js",
    f"{RAW}/{BREWER}/colorbrewer_schemes.js",
    "52e6a6edbbe4bbb95467cb84fb7db8fcbb1d6d219c975851c4c9d79334f00a41",
)
#: The licence beside ColorBrewer's export, which the colours are read from: its copyright
#: line and conditions, under the Apache licence of the repository.
BREWER_OWN = Source(
    "colorbrewer-export-LICENSE.txt",
    f"{RAW}/{BREWER}/export/LICENSE.txt",
    "aba881933999be3549b2171832a11a9dfad574243019df95c067ccf3d47b9649",
)
OKABE_ITO_CITATION = (
    "Okabe M, Ito K. Color Universal Design (CUD): how to make figures and presentations "
    "that are friendly to colorblind people. 2008. https://jfly.uni-koeln.de/color/ . The "
    "eight colours are the RGB values that page gives, written as hex codes."
)

#: The collections: where each lives, its licence as its own files state it, who holds it,
#: and what it says of colour-vision deficiency.
COLLECTIONS = {
    "MetBrewer": {
        "home": "https://github.com/BlakeRMills/MetBrewer",
        "licence": "CC0-1.0",
        "holder": "Blake Robert Mills",
        "about": "palettes from works at the Metropolitan Museum of Art, New York",
        "claims": "its palette list marks each colorblind = TRUE or FALSE",
    },
    "MoMAColors": {
        "home": "https://github.com/BlakeRMills/MoMAColors",
        "licence": "MIT",
        "holder": "MoMAColors authors (2023)",
        "about": "palettes from works at the Museum of Modern Art, New York",
        "claims": "its palette list marks each colorblind = TRUE or FALSE",
    },
    "NatParksPalettes": {
        "home": "https://github.com/kevinsblake/NatParksPalettes",
        "licence": "MIT",
        "holder": "Kevin S. Blake (2022)",
        "about": "palettes from photographs of national parks",
        "claims": "its palette list marks each colorblind = TRUE or FALSE",
    },
    "PNWColors": {
        "home": "https://github.com/jakelawlor/PNWColors",
        "licence": "CC0-1.0",
        "holder": "Jake Lawlor",
        "about": "palettes from photographs of the US Pacific Northwest",
        "claims": None,
    },
    "wesanderson": {
        "home": "https://github.com/karthik/wesanderson",
        "licence": "MIT",
        "holder": "Karthik Ram (2022)",
        "about": "palettes from the films of Wes Anderson",
        "claims": None,
    },
    "Okabe-Ito": {
        "home": "https://jfly.uni-koeln.de/color/",
        "licence": "published values",
        "holder": "Masataka Okabe and Kei Ito (2008), Color Universal Design",
        "about": "eight colours chosen to stay apart for readers with each common deficiency",
        "claims": "designed for readers with a colour-vision deficiency",
    },
    "ColorBrewer": {
        "home": "https://colorbrewer2.org",
        "licence": "Apache-2.0",
        "holder": "Cynthia A. Brewer, Mark Harrower and The Pennsylvania State University",
        "about": "schemes for maps, each given for every number of classes it offers",
        "claims": None,
    },
    "viridis": {
        "home": "https://github.com/BIDS/colormap",
        "licence": "CC0-1.0",
        "holder": "Nathaniel J. Smith and Stefan van der Walt",
        "about": "perceptually uniform maps drawn for matplotlib: viridis, magma, inferno, "
        "plasma",
        "claims": "drawn to stay readable with colour-vision deficiency and in grey",
    },
    "cividis": {
        "home": "https://github.com/pnnl/cmaputil",
        "licence": "BSD-style (Battelle Memorial Institute, 2017)",
        "holder": "Battelle Memorial Institute (Nuñez, Anderton and Renslow, PLoS ONE 2018)",
        "about": "viridis made to look the same to a reader with deuteranopia",
        "claims": "optimised for readers with a colour-vision deficiency",
    },
    "Crameri": {
        "home": "https://doi.org/10.5281/zenodo.8409685",
        "licence": "MIT",
        "holder": "Fabio Crameri, Scientific colour maps 8.0.1 (2023)",
        "about": "perceptually uniform maps for science, read from cmcrameri's copy of "
        "version 8.0",
        "claims": "readable by colour-vision deficient and colour-blind people",
    },
}

#: Okabe and Ito's eight, in the order their page gives them, as its RGB numbers.
OKABE_ITO = ((0, 0, 0), (230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66),
             (0, 114, 178), (213, 94, 0), (204, 121, 167))  # fmt: skip
#: How Crameri's version 8 user guide groups the maps that are neither categorical (`S`) nor
#: cyclic (`O`): the rest are sequential.
CRAMERI_DIVERGING = {"bam", "berlin", "broc", "cork", "lisbon", "managua", "roma", "tofino",
                     "vanimo", "vik"}  # fmt: skip
CRAMERI_MULTI = {"bukavu", "fes", "oleron"}
BREWER_KIND = {"div": "diverging", "seq": "sequential", "qual": "qualitative"}

_HEX = re.compile(r"""["'](#[0-9A-Fa-f]{6})["']""")
_LISTED = re.compile(
    r"(\w+)\s*=\s*list\(\s*c\(([^)]*)\)\s*,\s*c\(([^)]*)\)\s*,\s*colorblind\s*=\s*(\w+)\s*\)",
    re.DOTALL,
)
_BOUND = re.compile(r"(\w+)\s*=\s*rbind\(\s*c\(([^)]*)\)\s*,\s*c\(([^)]*)\)\s*\)", re.DOTALL)
_VECTOR = re.compile(r"(\w+)\s*=\s*c\(([^)]*)\)")


def _order(text: str, length: int) -> list[int]:
    """An R vector of positions, `c(2, 7, 5)` or `c(1:9)`, cut to the palette's length (two
    of MoMAColors' write one more position than they have colours)."""
    text = text.strip()
    if re.fullmatch(r"\d+\s*:\s*\d+", text):
        first, last = (int(n) for n in text.split(":"))
        found = list(range(first, last + 1))
    else:
        found = [int(n) for n in re.findall(r"\d+", text)]
    return found[:length]


def _listed(text: str, collection: str, prefix: str) -> dict:
    found = {}
    for name, codes, order, blind in _LISTED.findall(text):
        colours = [c.lower() for c in _HEX.findall(codes)]
        found[f"{prefix}/{name}"] = {
            "collection": collection, "kind": None, "colours": colours,
            "order": _order(order, len(colours)), "claims_cvd": blind.upper().startswith("T"),
        }  # fmt: skip
    return found


def _block(text: str, opens: str) -> str:
    """What `opens` opens, an R list's parenthesis or a Python list's bracket, up to the one
    that closes it."""
    start = text.index(opens) + len(opens)
    pair = {opens[-1]: 1, {"(": ")", "[": "]"}[opens[-1]]: -1}
    depth = 1
    for at in range(start, len(text)):
        depth += pair.get(text[at], 0)
        if depth == 0:
            return text[start:at]
    raise ValueError(f"{opens} is never closed")


def _pnw(text: str) -> dict:
    found = {}
    for name, codes, order in _BOUND.findall(_block(text, "pnw_palettes <- list(")):
        colours = [c.lower() for c in _HEX.findall(codes)]
        found[f"pnw/{name}"] = {
            "collection": "PNWColors", "kind": None, "colours": colours,
            "order": _order(order, len(colours)), "claims_cvd": None,
        }  # fmt: skip
    return found


def _wes(text: str) -> dict:
    return {
        f"wes/{name}": {"collection": "wesanderson", "kind": None,
                        "colours": [c.lower() for c in _HEX.findall(codes)], "order": None,
                        "claims_cvd": None}  # fmt: skip
        for name, codes in _VECTOR.findall(_block(text, "wes_palettes <- list("))
    }


def _brewer(text: str) -> dict:
    found = {}
    for name, scheme in json.loads(text).items():
        by_n = {
            n: [hex_of(parse(code)[0]) for code in codes]
            for n, codes in sorted(scheme.items(), key=lambda item: item[0])
            if n.isdigit()
        }
        largest = max(by_n, key=int)
        found[f"brewer/{name}"] = {
            "collection": "ColorBrewer", "kind": BREWER_KIND[scheme["type"]],
            "colours": by_n[largest], "order": None, "by_n": by_n, "claims_cvd": None,
        }  # fmt: skip
    return found


def _floats(rows: list[list[float]]) -> list[str]:
    return [hex_of((r, g, b)) for r, g, b in rows]


def _viridis(text: str) -> dict:
    found = {}
    for name in ("magma", "inferno", "plasma", "viridis"):
        body = _block(text, f"_{name}_data = [")
        rows = [[float(x) for x in row.split(",")] for row in re.findall(r"\[([^\[\]]+)\]", body)]
        found[f"viridis/{name}"] = {"collection": "viridis", "kind": "sequential",
                                    "colours": _floats(rows), "order": None,
                                    "claims_cvd": True}  # fmt: skip
    return found


def _table(text: str) -> list[str]:
    """A map written one colour to a line, as three numbers from 0 to 1."""
    rows = [[float(x) for x in line.split()] for line in text.splitlines() if line.strip()]
    return _floats(rows)


def _crameri(name: str, text: str) -> dict:
    if name.endswith("S"):
        kind = "qualitative"
    elif name.endswith("O"):
        kind = "cyclic"
    elif name in CRAMERI_DIVERGING:
        kind = "diverging"
    elif name in CRAMERI_MULTI:
        kind = "multi-sequential"
    else:
        kind = "sequential"
    return {"collection": "Crameri", "kind": kind, "colours": _table(text), "order": None,
            "claims_cvd": True}  # fmt: skip


def _text(folder: Path, source: Source) -> str:
    """The file `source` names, refused where it is not the one named."""
    data = (folder / source.file).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != source.sha256:
        raise SystemExit(f"{source.file} is not the file named here ({source.url}): its "
                         f"SHA-256 is {digest}, and {source.sha256} is expected")  # fmt: skip
    return data.decode("utf-8")


def licences(folder: Path) -> str:
    """Each collection's licence and notice, in its own words where its files hold them."""
    moma = _text(folder, LICENCE_FILES["MoMAColors"])
    permission = moma[moma.index("Permission is hereby granted"):].strip()
    parts = [
        "The palettes in palettes.json are their makers' work, under the licences below, each "
        "as the collection's own files give it. tools/derive_palettes.py wrote this file from "
        "those files, and wrote each palette's colours into palettes.json from its "
        "collection's file. The colours are as the collections give them; ColorBrewer's are "
        "written as hex codes where its file writes rgb(), and viridis's, cividis's and "
        "Crameri's as hex codes where theirs write numbers from 0 to 1.",
    ]
    for name, source in LICENCE_FILES.items():
        text = _text(folder, source).strip()
        if source.file.endswith("DESCRIPTION"):
            line = next(line for line in text.splitlines() if line.startswith("License:"))
            text = (f"{line.strip()} (the package's DESCRIPTION): the Creative Commons Zero "
                    "dedication, https://creativecommons.org/publicdomain/zero/1.0/")
        elif text.startswith("YEAR:"):
            fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
            text = (f"MIT License\n\nCopyright (c) {fields['YEAR'].strip()} "
                    f"{fields['COPYRIGHT HOLDER'].strip()}\n\n{permission}")
        if name == "ColorBrewer":
            head = _text(folder, BREWER_NOTICE)
            # The comment's words, without the asterisk that opens its second line.
            words = head[head.index("This product"):head.index(")") + 2].split()
            notice = " ".join(word for word in words if word != "*")
            own = _text(folder, BREWER_OWN).strip()
            text = (f"{notice}\n\n{own}\n\nThe Apache License, Version 2.0, as the "
                    f"repository gives it:\n\n{text}")
        about = COLLECTIONS[name]
        parts.append(f"{'=' * 78}\n{name}: {about['home']}\n{'=' * 78}\n\n{text}")
    parts.append(f"{'=' * 78}\nOkabe-Ito: {COLLECTIONS['Okabe-Ito']['home']}\n{'=' * 78}\n\n"
                 f"{OKABE_ITO_CITATION}")  # fmt: skip
    return "\n\n".join(parts) + "\n"


def read(folder: Path) -> dict:
    texts = {key: _text(folder, source) for key, source in SOURCES.items()}
    found = {}
    found.update(_listed(texts["met"], "MetBrewer", "met"))
    found.update(_listed(texts["moma"], "MoMAColors", "moma"))
    found.update(_listed(texts["natparks"], "NatParksPalettes", "natparks"))
    found.update(_pnw(texts["pnw"]))
    found.update(_wes(texts["wes"]))
    found["okabe-ito"] = {"collection": "Okabe-Ito", "kind": "qualitative",
                          "colours": [hex_of(tuple(c / 255 for c in rgb)) for rgb in OKABE_ITO],
                          "order": None, "claims_cvd": True}  # fmt: skip
    found.update(_brewer(texts["brewer"]))
    found.update(_viridis(texts["viridis"]))
    found["cividis/cividis"] = {"collection": "cividis", "kind": "sequential",
                                "colours": _table(texts["cividis"]), "order": None,
                                "claims_cvd": True}  # fmt: skip
    for name in CRAMERI_MAPS:
        found[f"crameri/{name}"] = _crameri(name, texts[f"crameri/{name}"])
    return found


def derive(folder: Path) -> str:
    found = read(folder)
    for entry in found.values():
        entry.update(palettes.assess(entry))
    document = {
        "schema": "manuscript-guard/palettes/1",
        "written_by": "tools/derive_palettes.py, from the files named in it; not by hand",
        "collections": {
            name: {**about, "sources": sorted(
                s.url for key, s in SOURCES.items()
                if _collection_of(key) == name
            )}
            for name, about in COLLECTIONS.items()
        },  # fmt: skip
        "palettes": dict(sorted(found.items())),
    }
    return _written(document)


def _written(document: dict) -> str:
    """The document as JSON, each palette on a line of its own: a diff of the file then
    shows which palettes changed, and it is a third of the size it is one value a line."""
    held = document["palettes"]
    head = json.dumps({**document, "palettes": {}}, indent=1, ensure_ascii=False)
    lines = [f" {json.dumps(name)}: {json.dumps(entry, ensure_ascii=False)}"
             for name, entry in held.items()]  # fmt: skip
    body = "{\n" + ",\n".join(lines) + "\n }"
    return head.replace('"palettes": {}', '"palettes": ' + body) + "\n"


def _collection_of(key: str) -> str:
    return {
        "met": "MetBrewer", "moma": "MoMAColors", "natparks": "NatParksPalettes",
        "pnw": "PNWColors", "wes": "wesanderson", "brewer": "ColorBrewer",
        "viridis": "viridis", "cividis": "cividis",
    }.get(key.split("/")[0], "Crameri")  # fmt: skip


def fetch(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for source in [*SOURCES.values(), *LICENCE_FILES.values(), BREWER_NOTICE, BREWER_OWN]:
        with urllib.request.urlopen(source.url, timeout=60) as answer:  # noqa: S310
            (folder / source.file).write_bytes(answer.read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="where the collections' files are kept")
    parser.add_argument("--fetch", action="store_true", help="download them there first")
    args = parser.parse_args(argv)
    if args.fetch:
        fetch(args.folder)
    written = {OUT: derive(args.folder), R_OUT: None,
               LICENCES_OUT: licences(args.folder), R_LICENCES_OUT: None}  # fmt: skip
    written[R_OUT], written[R_LICENCES_OUT] = written[OUT], written[LICENCES_OUT]
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
