"""Append a small, independently verified set of named cultural places offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archsearch.domain import Site
from archsearch.supplement_data import (
    CoordinateEvidence,
    IdentityReview,
    SourceArtifact,
    base_contract,
)

DATA_DIR = Path(__file__).with_name("data")
VERSION = "named-places-v1"
CORPUS_VERSION = "global-v19"
SPEC_FILE = "target_review.json"
SITES_FILE = "target_sites.json"
MANIFEST_FILE = "target_manifest.json"
SPEC_SHA256 = "636dd971a74da8e0bfd92028fedf7a29a696c318a761913e6900709800fbe9b0"
SITES_SHA256 = "6764fe78b83500fe5a7b58a270c329d52d31ee51d42b096a8df024d0d4f129d3"
MAX_ARTIFACT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NamedPlaceCohort:
    version: str
    corpus_version: str
    file_prefix: str
    review_sha256: str
    sites_sha256: str
    country_labels: tuple[tuple[str, str], ...] = ()

    @property
    def filenames(self) -> tuple[str, str, str]:
        prefix = self.file_prefix
        return f"{prefix}_review.json", f"{prefix}_sites.json", f"{prefix}_manifest.json"


ORIGINAL = NamedPlaceCohort(VERSION, CORPUS_VERSION, "target", SPEC_SHA256, SITES_SHA256)
GUYANA = NamedPlaceCohort(
    "guyana-named-places-v1",
    "global-v20",
    "guyana",
    "b60e4d13bd63e7ea1a74085a4931925fba0c7910d76778497346819923618904",
    "42309086e8ed2a5f01f92e68d6bd09529dc28ea5b75d2946348fb578a5831a80",
)
IRELAND = NamedPlaceCohort(
    "ireland-public-monuments-v1",
    "global-v21",
    "ireland_nms",
    "be4cfaff8cb0aec3818dabf42eecda07b0fe3635439bbe9912988c9782deeb99",
    "323e9e5300416db7337fb177df017b60f6d35edddbd7970168c86537b17c7902",
)
ANDALUCIA = NamedPlaceCohort(
    "andalucia-reca-v1",
    "global-v21",
    "andalucia_reca",
    "b518958cec6782751bb246d32979c06b9186c493171bcc783defc73e2c6bdc75",
    "35fff33b680ce7a40991976fee121bd0beeeba1800d09c82b8be04984c87f321",
)
TAIWAN_ICULTURE = NamedPlaceCohort(
    "taiwan-iculture-v1",
    "global-v21",
    "taiwan_iculture",
    "0ddff3d9dd12b60cc7f54d23fef8c10ab4d514723c9f0119422fdf80db193075",
    "860b2e16629089779e33699a8ba7f6bd06c3fdc020e934c88bc8ce824e4bb8ca",
    country_labels=(("TW", "Taiwan"),),
)
MEXICO_SIC = NamedPlaceCohort(
    "mexico-sic-public-archaeology-v1",
    "global-v21",
    "mexico_sic",
    "45793ce985a6ba2dd4035c9b58d7786943872ee5287a97d4f77c18162fbd08b4",
    "9f1b3d27dfcfe2ed2b631e9f3cd140c8c660425fa4d2e5d4b2e46d7a87753286",
)
FINLAND_VARK = NamedPlaceCohort(
    "finland-vark-public-v1",
    "global-v21",
    "finland_vark",
    "9d487a5e46f31f671254b4ae7184a0c245c178265cdf53b83a97b11eaeb290b8",
    "fb4e142b0f9517ae9e82328f8394c7d985692efb84a846b855cab476ce5270fa",
)
WALES_CADW = NamedPlaceCohort(
    "wales-cadw-public-v1",
    "global-v21",
    "wales_cadw",
    "800a7f09b32eb1d0a0e605895e42d60c5b6073a1ffe4a32470333669c3ecafd4",
    "f142e838e97dcd2545fc52c36827f0dbc448722c8ef6a58a96d0cf42ef435eb7",
)
THAILAND_FAD = NamedPlaceCohort(
    "thailand-fad-public-v1",
    "global-v21",
    "thailand_fad",
    "1cc7aecfdb0cb1b2925e15c4dc4c6587b8d6451b19a1a2e63929fc371f0fc44c",
    "9ee26d0b20abf35338d93430a812c06df435bffe827654d4081154d1670c08d4",
)
AFRICA_VISIT = NamedPlaceCohort(
    "africa-public-visit-v1",
    "global-v21",
    "africa_visit",
    "184d58133b5930819d4209057789071e0998c8a88b09434934403364a7fd3d76",
    "f16570a0fe066763579adadc8b440622378bce8cffa3bd23e4a7a10ab6788155",
)
SCOTLAND_HES = NamedPlaceCohort(
    "scotland-hes-public-v1",
    "global-v21",
    "scotland_hes",
    "1db3d61d10a10bc8d59c6fb725b21a99b7b564a46da46578c896b4551e902e86",
    "b8b553b4026ce9ac1f2def85457fd85c300f6651e636d96e1f5db8797dd04723",
)
CARIBBEAN_NRHP = NamedPlaceCohort(
    "caribbean-nrhp-public-v1",
    "global-v21",
    "caribbean_nrhp",
    "697c34f8caf877b70fda7f2f7b47d1803ce8bbad414d8c8a40d936480916c88c",
    "8899b0b29eec454e2e7f1f71241c02a01ee809319dafb49dc8992ae0c1f3e2d3",
    country_labels=(("PR", "Puerto Rico"), ("VI", "United States Virgin Islands")),
)
PERU_PUBLIC = NamedPlaceCohort(
    "peru-mincul-public-v1",
    "global-v21",
    "peru_public",
    "fd042f30ff3f8719364f132e085b2d019c08d10920833e18ed62ef0fd37eba77",
    "b77b25d193ba22505e0255a93863e794eb2ab8a70e822a5f8f83d7c1708f1dcf",
)
INDIA_ASI = NamedPlaceCohort(
    "india-asi-public-v1",
    "global-v21",
    "india_asi",
    "df0e2c551a3a2a96686f0b595221bdb935d3c4d930d80442474c4b93e8763d37",
    "3647c59d3957018304bd9226faa2faa9792648de152aa27eeeb2684fcfc49c4d",
)
INDIA_ASI_NEXT = NamedPlaceCohort(
    "india-asi-public-v2",
    "global-v21",
    "india_asi_next",
    "71a5d01e639267be7c014e654d14a0e290dc16a765a10a8012049e3d45d1dbd8",
    "5fc2ecb2d575c6b6ae51fbab98cc03f5b250bda39589751363ff71d31f66c7a6",
)
SRI_LANKA_PUBLIC = NamedPlaceCohort(
    "sri-lanka-public-v1",
    "global-v21",
    "sri_lanka_public",
    "c70da6586e71c743f37f43dbe8a3c5c8fd4e9ba3ffd771d6ac14a4ba5f3ae3d9",
    "0b369ab2c8cf1e7bfc3054a7cada630153a8855a90ec204a1148307c208f4489",
)
SOUTH_ASIA_PUBLIC = NamedPlaceCohort(
    "south-asia-bd-np-pk-public-v1",
    "global-v21",
    "south_asia_public",
    "70cd25abac05104b6f7be6661a50a8dd5105c5117377433436331d676d7a72b9",
    "298a855b6905f736f209ab6674587f77953df0106341997c7913143eb49e23f0",
)
CENTRAL_AMERICA_PUBLIC = NamedPlaceCohort(
    "public-central-america-colombia-v1",
    "global-v21",
    "central_america_public",
    "03aa02e5faf3c14747413a1a62e0d431a5a28509b3398690851973a60d7ee517",
    "1fd5f68277153eff34d2e7d48d52ddc956ee3c22ed9432759891e350c1b5388f",
)
SOUTHERN_PUBLIC = NamedPlaceCohort(
    "southern-cone-public-v1",
    "global-v21",
    "southern_public",
    "97706bbef72a4c30d511fdf5ba73bb5e782b3e535eb44759741e0864f1f503d8",
    "8606c50ab848729252bc30c9c711e5c4cecd6410a7cbc5eb26ba9d820aa4e17f",
)
NEW_ZEALAND_PUBLIC = NamedPlaceCohort(
    "new-zealand-public-v1",
    "global-v21",
    "new_zealand_public",
    "ca03ffffdb79bb4c43d3f22e5d0bbf1884bf8cac213cb9df77b6bee4f77b3dc3",
    "dba29f8e7562b2df0f30787353a143f3c8b78cb05938a00af8fac9c4ea3534dd",
)
EGYPT_PUBLIC = NamedPlaceCohort(
    "egypt-mota-public-v1",
    "global-v21",
    "egypt_public",
    "89a99e29afb86070b703281471219c5454ea127554ac9b9da83b0382cb6df3d6",
    "fbfb0317e370df2f3f0fd4601ca2f6a00a130d10324733cdbc106f1bbb815c3e",
)
SOUTHEAST_PUBLIC = NamedPlaceCohort(
    "vietnam-cambodia-public-v1",
    "global-v21",
    "southeast_public",
    "5cb9406321605edf6c7a3fb96affc7a9fba9519712605caf6484fdd14dff348b",
    "261a0aa22efe6beb61a518944538dcddeee6d416e4c866813dd543da7ccdc974",
)
CARIBBEAN_ISLANDS_PUBLIC = NamedPlaceCohort(
    "caribbean-islands-public-v1",
    "global-v21",
    "caribbean_islands_public",
    "ca91998d3226028b7f9272a684fce9048a2de5fe073a32023fa72ea730233136",
    "7bd2b413ce2ef6cb8139bc2002cd30b6c4ef87aed1eaa9e2f78314b20de61c14",
)
TUNISIA_PUBLIC = NamedPlaceCohort(
    "tunisia-amvppc-public-v1",
    "global-v21",
    "tunisia_public",
    "4f69a96aa81163c5c60d4eaafa032eec198dde0d74aaa84d329dedfedfeee243",
    "89ccb4b61061707fb118c139dfd0f1cc54cc1b2540b6b045cb145008c0583b9c",
)
MOROCCO_PUBLIC = NamedPlaceCohort(
    "morocco-public-v1",
    "global-v21",
    "morocco_public",
    "b344ca464c90c8df4fab286604bdbcfacfa6e800d8f909233dcf69e77d260f65",
    "4a7d7186e52702bb0eb7c01ff2a28237d9f1cf7363f250e8e6fe9a4bc00acc9a",
)
NORTH_CENTRAL_PUBLIC = NamedPlaceCohort(
    "north-central-america-public-v1",
    "global-v21",
    "north_central_public",
    "e23c43b1b7a06fc8716472613810bc05c841b0bd1c72c489e7bc87d0b08a4bae",
    "0c484da970e39f89bda49cecb495eee01f16df5c195f058e031290e00073c692",
)
PACIFIC_ISLANDS_PUBLIC = NamedPlaceCohort(
    "pacific-islands-public-v1",
    "global-v21",
    "pacific_islands_public",
    "b61c75a75a93a2eaf1d6bee29f28311aa4e62a4e8c938cbd483b407dd0125d48",
    "f48e2fad24bab384a826c9885413f4ce6e7298f03f0d82c6bbb524e3207fd87b",
)
EAST_AFRICA_PUBLIC = NamedPlaceCohort(
    "tanzania-uganda-public-v1",
    "global-v21",
    "east_africa_public",
    "c68fd862dd7caad2f6e351159c186c9072dacc9bd3e5fa21c928947776e3d904",
    "2522b3601149e8289d86fdf75bbac046d4afd362df00017bab3a8aaaf10907b9",
)
KENYA_PUBLIC = NamedPlaceCohort(
    "kenya-nmk-public-v1",
    "global-v21",
    "kenya_public",
    "c5334adb77f40a3f3127ce99654541e11fd0036961e5b44761062c66ce3027e0",
    "24a0ce444669cfb70e31856df0f3429ee6e14da741e40d570a7d1bd6857d6a9e",
)
RIVER_PLATE_PUBLIC = NamedPlaceCohort(
    "uruguay-paraguay-public-v1",
    "global-v21",
    "river_plate_public",
    "a692b95b91fdb084f96d54b87f98445598b43360d5ced82ad8155ce7ed3de149",
    "40671f78f50f735966c246bf0df18f82e626f828b569b141fb461ec41da120e1",
)
CENTRAL_ASIA_PUBLIC = NamedPlaceCohort(
    "kazakhstan-uzbekistan-public-v1",
    "global-v21",
    "central_asia_public",
    "ab9d4632b74b58889c197ce9a2a553409d6d6670afc83970f332f6da6084477b",
    "e87bf1088d402513a9cf8102cdd475d25ff046e710a6d197414b63f25dba2a99",
)
ENGLAND_NHLE = NamedPlaceCohort(
    "england-nhle-public-v1",
    "global-v21",
    "england_nhle",
    "a5af2649aa2269dc224ee46e2e83740e2174221e0c709ec85699aa5a9c330b01",
    "cdbc62fa05de8df2b6e581202aa181995f12517ecfbc591c7a40e944fcd027d8",
)
CENTRAL_SOUTH_PUBLIC = NamedPlaceCohort(
    "ecuador-bolivia-brazil-guyana-public-v1",
    "global-v21",
    "central_south_public",
    "3764b07ae67ebb1950dc276a530583886196f93f514ffe1f29eb4c1eca30736f",
    "d7a61776796da2bf57cfe166334712ac9f3753da656520dfe62a38af7faded94",
)
NORWAY_ASKELADDEN = NamedPlaceCohort(
    "norway-askeladden-public-v1",
    "global-v21",
    "norway_askeladden",
    "9d549f51941973329f4333ae8246115196aeca4b9d3ded44193a37d4ed64c3ec",
    "db04050dae9eaf754faeb13ce981fe97fd96d3d62b7ea19a1e4570d6e3174b27",
)
JAPAN_PUBLIC = NamedPlaceCohort(
    "japan-public-heritage-v1",
    "global-v21",
    "japan_public",
    "934caed564b481cf3cb613d04a6a01917c0f83f920c541d28b51fb4a8303fc9e",
    "b8be883727c868de1703a622867010343ba18374cc221bfd1df91ab2e916c8f6",
)
SOUTHERN_AFRICA_PUBLIC = NamedPlaceCohort(
    "namibia-botswana-zimbabwe-zambia-public-v1",
    "global-v21",
    "southern_africa_public",
    "33fcb3cb5cbf8714af1ca4688a9f80bd74b283eacd92695223d0d47a16d9cc51",
    "e928b56e4f9be402f3b0699fef6f8a3c445a6df414368d6c01a92a4c5aebea31",
)
INDONESIA_ISLANDS_PUBLIC = NamedPlaceCohort(
    "indonesia-islands-public-v1",
    "global-v21",
    "indonesia_islands_public",
    "4d29f252232e3c4b3df2844f6d2d16aa00c89f7670512e5d58a9b5aad91870e3",
    "d30298be8c6d42119c39b19ff6abcc285eabcee392c7486b728738bf47c1d325",
)
KYRGYZ_TAJIK_PUBLIC = NamedPlaceCohort(
    "kyrgyzstan-tajikistan-public-v1",
    "global-v21",
    "kyrgyz_tajik_public",
    "01fef86d0d9035655499f940f4854c8ca1f9ab0b7dd595c520e2e55d1e3f5c82",
    "7b9298950ea930c358a1b30c161b41303cdcf04941531e0d900f7a5cc4c9608c",
)
NORTHERN_IRELAND_DFC = NamedPlaceCohort(
    "northern-ireland-dfc-public-v1",
    "global-v21",
    "northern_ireland_dfc",
    "f4193e62fda2b351206dda20e1157f60262e03d987bba51a97977ef7394665ed",
    "c643d62ec4699b43a242a0a25d8ebc022b76f6d98dd10e55b3d1cfe4aa1df929",
)
FRANCOPHONE_WEST_PUBLIC = NamedPlaceCohort(
    "senegal-benin-togo-public-v1",
    "global-v21",
    "francophone_west_public",
    "33b563ba60fae8ad9b851f70de2482e2c8c01bb29841e176d795440d4b96a90d",
    "7e46fa2d6d63700a0caf1ebc56ab20bacf367e01050e7c7f2a0b87568e1e19a9",
)
GHANA_NIGERIA_PUBLIC = NamedPlaceCohort(
    "ghana-nigeria-public-v1",
    "global-v21",
    "ghana_nigeria_public",
    "5669e6e1c43ee5acd492f18d231a8e93f4123ffca73421da5b282041b7a8ec2e",
    "03baa8015832255190176f1b87e9032dc60f0488e48603840e0c2e1cb70f56b2",
)
PH_EAST_MY_PUBLIC = NamedPlaceCohort(
    "philippines-east-malaysia-public-v1",
    "global-v21",
    "ph_east_my_public",
    "dd068d8e93a0d60f76ab2c6cf85cc42037a370ab2087d9b6264250b656cbebb7",
    "fdae60e4c406177db144c42b6cb1303747c9199e33c655e8db8890740a874f55",
)
BALTIC_PUBLIC = NamedPlaceCohort(
    "estonia-latvia-public-v1",
    "global-v21",
    "baltic_public",
    "46f94420053f7996e609d1ccb4b830e3bc4d021c61eb05c4490b6ab428a94676",
    "8d67bbc07f2c9053809a2bb00810bd54072cbb0879f8b613ac44e306e7c36761",
)
BALKAN_PUBLIC = NamedPlaceCohort(
    "albania-north-macedonia-public-v1",
    "global-v21",
    "balkan_public",
    "d9ca3c0608284442dab7b4ef959c10a18909478d9e56a3bace9ff0f330048349",
    "a7cde0e92650c8eefae6590e07090d6d7e899fa2ea28f38d76c4120affd58bd6",
)
GULF_PUBLIC = NamedPlaceCohort(
    "oman-bahrain-qatar-public-v1",
    "global-v21",
    "gulf_public",
    "2ad6a4595462a3fe590ac2b0d9c439d054c6a432cf708c65e516ebb37e330133",
    "dc702c78fa34f1f9474c339b413622f74a121e617a7c7b880103bf9cf3a6b88d",
)
CAUCASUS_PUBLIC = NamedPlaceCohort(
    "georgia-armenia-public-v1",
    "global-v21",
    "caucasus_public",
    "26bb7af9b0c2fe4fca71b9439b892e116f96fb0144a7b95255af3ef1331b30f2",
    "69794e6d8fdc74545310257e5cda49a0851998073c99278439143755a8678236",
)
LITHUANIA_PUBLIC = NamedPlaceCohort(
    "lithuania-kvr-public-v1",
    "global-v21",
    "lithuania_public",
    "155e8c069beb5799d9a5c9031584a8c0aa9bec9a402a77ea3a81c7afd1885d91",
    "7deef1f035aae55549a6af934c6112c2095dd9928db2d5c2a71687010deba52b",
)
DENMARK_PUBLIC = NamedPlaceCohort(
    "denmark-public-v1",
    "global-v21",
    "denmark_public",
    "336d0724e43bef33e6ea3a589603f1da09f4a61e0df5162715aaa0bdbeab29f7",
    "5256b7831484ab2c6fb673151404e64847df2423835052570310cf13426ba3b9",
)
MONGOLIA_PUBLIC = NamedPlaceCohort(
    "mongolia-public-v1",
    "global-v21",
    "mongolia_public",
    "12f942adc28f479545a567c8e2934309b4e33ae4e61c0745ff2d3408aa20938c",
    "f8cfc5e1fe21c38d5b1dba8477009591242616fcf508548d405628caf8acc2ff",
)
PORTUGAL_PUBLIC = NamedPlaceCohort(
    "portugal-public-v1",
    "global-v21",
    "portugal_public",
    "c8bbc1ee04978230f2d6d928e29b3d39c9145f2035d9c31398867610816aa7bf",
    "7ea1297edd23f31cac514e984d32c3995c411bc552302dd31bdf5ed5f4c14803",
)
DANUBE_PUBLIC = NamedPlaceCohort(
    "moldova-romania-public-v1",
    "global-v21",
    "danube_public",
    "e90334e75042767c74f8d8b582684a41be2f8fa6d91b74e4b0f91792a8b0cccb",
    "e50b7dd7c0a729238355a38888bf1b1b03c5f9620673c66722d227a3ac517bce",
)
ISLANDS_SECOND_PUBLIC = NamedPlaceCohort(
    "public-pacific-and-atlantic-islands-v2",
    "global-v21",
    "islands_second_public",
    "337dbbc84fa8ffa898a8393204848d5e667898f2d9d198cbc341f4099d51103c",
    "2387d930517c66a1bac08047a70a8d752d718c514a5b146827e57ae416165ada",
    country_labels=(("BM", "Bermuda"), ("KY", "Cayman Islands")),
)
KOREA_GANGWON_PUBLIC = NamedPlaceCohort(
    "korea-gangwon-public-v1",
    "global-v21",
    "korea_gangwon_public",
    "b08490b90bab18cd11503a7cc5221ba127418f99752a8185a7b9bbc642f48fa3",
    "3a356ee1eff9228aab550f5134175f8a3059292158665331b51674be6a811843",
)
BULGARIA_SERBIA_PUBLIC = NamedPlaceCohort(
    "bulgaria-serbia-public-v1",
    "global-v21",
    "bulgaria_serbia_public",
    "e9d8afcb0b54af67c7ae2b3b0ba075e80eadad75184d4ef12d8025224063ee38",
    "98201c036b09e190d5ebe3b1d389437effbe93fae1b61a594d678b528581a0bb",
)
RWANDA_PUBLIC = NamedPlaceCohort(
    "rwanda-public-v1",
    "global-v21",
    "rwanda_public",
    "30ac9e7813737a75cb340a4207571be2fec5ecf8b861d8688e8fedfeb51c9dbb",
    "4d3f008417a47a089c3631fe25e56fc200a9b0d2b30b9ab1f49f8df5e516bb0f",
)
LAOS_BHUTAN_PUBLIC = NamedPlaceCohort(
    "laos-bhutan-public-v1",
    "global-v21",
    "laos_bhutan_public",
    "5e62bbdaf524f2556dd0deb8d416241a52e2410f4dd6fc5fd0bfed679b990d2a",
    "85d98c35f18dbc6c710303817ba629a8d37116de41ca6b9465532798414ce74c",
)
ALGERIA_PUBLIC = NamedPlaceCohort(
    "algeria-public-v1",
    "global-v21",
    "algeria_public",
    "ec4836b0427e3f0deec415097138d4f446f8745deabd5aa5a0068f671271c577",
    "09f369cd3f52df723d8654364332d926b583ac30c11b47b061f4da58d67f8c88",
)
SWEDEN_PUBLIC = NamedPlaceCohort(
    "sweden-public-v1",
    "global-v21",
    "sweden_public",
    "eae9fa1ac05584db8915e67154129063936470295b9b91d71e0e9d0a3b3a333d",
    "bfd265bd401279e427f2b6333c45c5a52cf38532929489b2ac13c7ab362dfae3",
)
POINT_COHORTS = (
    IRELAND, ANDALUCIA, TAIWAN_ICULTURE, MEXICO_SIC, FINLAND_VARK, WALES_CADW, THAILAND_FAD,
    AFRICA_VISIT, SCOTLAND_HES, CARIBBEAN_NRHP, PERU_PUBLIC, INDIA_ASI, INDIA_ASI_NEXT,
    SRI_LANKA_PUBLIC, SOUTH_ASIA_PUBLIC, CENTRAL_AMERICA_PUBLIC, SOUTHERN_PUBLIC,
    NEW_ZEALAND_PUBLIC, EGYPT_PUBLIC, SOUTHEAST_PUBLIC, CARIBBEAN_ISLANDS_PUBLIC,
    TUNISIA_PUBLIC, MOROCCO_PUBLIC, NORTH_CENTRAL_PUBLIC, PACIFIC_ISLANDS_PUBLIC,
    EAST_AFRICA_PUBLIC, KENYA_PUBLIC, RIVER_PLATE_PUBLIC, CENTRAL_ASIA_PUBLIC, ENGLAND_NHLE,
    CENTRAL_SOUTH_PUBLIC, NORWAY_ASKELADDEN, JAPAN_PUBLIC, SOUTHERN_AFRICA_PUBLIC,
    INDONESIA_ISLANDS_PUBLIC, KYRGYZ_TAJIK_PUBLIC, NORTHERN_IRELAND_DFC,
    FRANCOPHONE_WEST_PUBLIC, GHANA_NIGERIA_PUBLIC, PH_EAST_MY_PUBLIC,
    BALTIC_PUBLIC,
    BALKAN_PUBLIC,
    GULF_PUBLIC,
    CAUCASUS_PUBLIC,
    LITHUANIA_PUBLIC,
    DENMARK_PUBLIC,
    MONGOLIA_PUBLIC,
    PORTUGAL_PUBLIC,
    DANUBE_PUBLIC,
    ISLANDS_SECOND_PUBLIC,
    KOREA_GANGWON_PUBLIC,
    BULGARIA_SERBIA_PUBLIC,
    RWANDA_PUBLIC,
    LAOS_BHUTAN_PUBLIC,
    ALGERIA_PUBLIC,
    SWEDEN_PUBLIC,
)


class TargetDataError(RuntimeError):
    """Named-place evidence or its frozen base corpus differs from its reviewed snapshot."""


class TargetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site: Site
    coordinate: CoordinateEvidence
    independent_review: IdentityReview
    source_files: list[SourceArtifact] = Field(min_length=1)
    scope_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> TargetRecord:
        site = self.site
        if (
            site.source_kind != "supplement"
            or site.types not in (["historic-site"], ["archaeological-site"])
            or site.periods or site.period_evidence or site.geography is None
            or site.chronology.status == "not_reviewed" or site.location_precision is not None
            or site.repr_point != self.coordinate.point
        ):
            raise ValueError("named places need their own reviewed scope, point and event evidence")
        if self.coordinate.source_uri is not None and not any(
            ref.uri == self.coordinate.source_uri for ref in site.source_refs
        ):
            raise ValueError("the representative point must retain its public source")
        artifacts = {artifact.uri for artifact in self.source_files}
        references = [*site.source_refs, *(source for phase in site.chronology.phases
                                         for source in phase.sources), site.geography.source]
        if any(ref.uri not in artifacts for ref in references):
            raise ValueError("all public source references need a checksummed retrieved artifact")
        excerpts: dict[str, set[str]] = {}
        for ref in references:
            if ref.license not in {"CC0", "CC0-1.0", "CC BY 4.0", "CC BY-SA 4.0"}:
                excerpts.setdefault(ref.uri, set()).add(ref.excerpt)
        if any(sum(len(text.split()) for text in texts) > 25 for texts in excerpts.values()):
            raise ValueError("short authority excerpts must stay within25 words per source")
        return self


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    cohort_version: str
    corpus_version: str
    base_count: int = Field(gt=0)
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[TargetRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise TargetDataError("named-place artifact exceeds its compact snapshot limit")
    return raw


def _compile(
    base: list[Site], directory: Path, cohort: NamedPlaceCohort,
) -> tuple[list[Site], bytes, dict[str, Any]]:
    spec_file, sites_file, _ = cohort.filenames
    raw = _read(directory / spec_file)
    if _hash(raw) != cohort.review_sha256:
        raise TargetDataError("named-place review differs from its independent checksum")
    spec = TargetSpec.model_validate_json(raw)
    if (spec.cohort_version, spec.corpus_version) != (cohort.version, cohort.corpus_version):
        raise TargetDataError("named-place review belongs to another cohort or corpus version")
    base_facts = base_contract(base)
    if any(getattr(spec, key) != value for key, value in base_facts.items()):
        raise TargetDataError("named-place base identities or fields changed")
    additions = sorted((record.site for record in spec.records), key=lambda site: site.id)
    ids = [site.id for site in [*base, *additions]]
    if len(ids) != len(set(ids)):
        raise TargetDataError("named places duplicate an existing corpus identity")
    payload = _bytes([site.model_dump(mode="json") for site in additions])
    if _hash(payload) != cohort.sites_sha256:
        raise TargetDataError("named-place derivative differs from the reviewed checksum")
    manifest = {
        "schema_version": 1, "cohort_version": cohort.version,
        "corpus_version": cohort.corpus_version,
        **base_facts,
        "files": {spec_file: {"sha256": cohort.review_sha256},
                  sites_file: {"sha256": cohort.sites_sha256}},
        "counts": {"added": len(additions), "total": len(base) + len(additions)},
        "selection": spec.selection,
        "processing": "Source-based bilingual summaries; no generated dates or coordinates. "
                      "Representative points retain their source scope; no inferred boundaries.",
    }
    return additions, payload, manifest


def load_targets(
    base: list[Site], data_dir: Path = DATA_DIR, *, cohort: NamedPlaceCohort = ORIGINAL,
) -> list[Site]:
    """Validate and append the frozen named-place cohort without reading source caches."""
    try:
        _, sites_file, manifest_file = cohort.filenames
        additions, payload, manifest = _compile(base, data_dir, cohort)
        if (_read(data_dir / sites_file) != payload
                or json.loads(_read(data_dir / manifest_file)) != manifest):
            raise TargetDataError("named-place shipped files do not match their reviewed facts")
        return [*base, *additions]
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise TargetDataError("named-place evidence is absent or invalid") from error


def rebuild_targets(
    base: list[Site], data_dir: Path = DATA_DIR, *, cohort: NamedPlaceCohort = ORIGINAL,
) -> dict[str, Any]:
    """Rebuild deterministic public artifacts from the compact, reviewed evidence."""
    _, sites_file, manifest_file = cohort.filenames
    _, payload, manifest = _compile(base, data_dir, cohort)
    (data_dir / sites_file).write_bytes(payload)
    (data_dir / manifest_file).write_bytes(_bytes(manifest))
    return manifest


def main() -> None:
    from archsearch.corpus import (
        load_guyana_corpus,
        load_named_places_v1_corpus,
        load_pre_targets_corpus,
    )

    parser = argparse.ArgumentParser(description="重建已复核的专名地点资料")
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    batches = parser.add_mutually_exclusive_group()
    batches.add_argument("--guyana", action="store_true", help="重建圭亚那批次")
    batches.add_argument(
        "--cohort", choices=[cohort.file_prefix for cohort in POINT_COHORTS],
        help="重建指定的公共点位批次",
    )
    args = parser.parse_args()
    if args.cohort:
        base = load_guyana_corpus()
        for cohort in POINT_COHORTS:
            if cohort.file_prefix == args.cohort:
                break
            base = load_targets(base, cohort=cohort)
    elif args.guyana:
        base, cohort = load_named_places_v1_corpus(), GUYANA
    else:
        base, cohort = load_pre_targets_corpus(), ORIGINAL
    print(json.dumps(rebuild_targets(base, args.output, cohort=cohort),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
