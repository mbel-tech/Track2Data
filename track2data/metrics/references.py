"""
Canonical bibliography for Track2Data's metric citations.

Every ``Reference`` below is a single verified work -- author, year,
journal, volume, pages, and DOI checked against the Crossref API
during the 2026-08 reference audit. Metrics point at these *objects*
(``MetricDocumentation.primary_reference`` /
``.supporting_references``, see ``base.py``) rather than retyping
citation text, so two metrics that cite the same work produce
byte-identical text by construction -- the alternative, hand-copying a
citation string into each metric class, is exactly how GL-1 ended up
carrying Couzin et al. 2002's DOI under a citation naming a different
paper entirely (see ``tests/test_metric_references_consistency.py``
::test_no_doi_is_shared_by_metrics_citing_different_works).

Only works that are actually cited by a built-in metric belong here.
A metric with no specific originating work (e.g. "Standard
kinematics") sets ``citation`` directly instead -- inventing a
``Reference`` for a generic convention would misrepresent it as having
one paper behind it, which is precisely the failure mode the audit
flagged in the other direction (a citation naming a paper that does
not actually support the metric).

``scripts/generate_metric_references.py`` walks every ``Reference``
reachable from the metric registry to emit ``docs/references.bib``,
so the four BibTeX-only fields (``entry_type``, ``author``, ``title``,
``publisher``) must be filled in even though the UI and CSV only ever
render ``text``/``doi``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Reference(BaseModel):
    """One verified, citable work."""

    key: str  # BibTeX cite key, e.g. "cachat2010"
    text: str  # canonical display citation (what the UI and CSV show)
    doi: str | None = None
    entry_type: Literal["article", "book", "incollection"] = "article"
    author: str
    title: str
    year: int
    journal: str | None = None
    volume: str | None = None
    pages: str | None = None
    publisher: str | None = None


def format_reference(ref: Reference) -> str:
    """Render one ``Reference`` the way the UI, the CSV, and
    ``METRICS_SPEC.md`` all show it -- one canonical format used
    everywhere a reference is rendered, so there is only one string to
    keep in sync rather than three copy-pasted formatting rules."""
    return f"{ref.text} (DOI: {ref.doi})" if ref.doi else ref.text


def format_supporting_references(refs: list[Reference]) -> str:
    """Render a metric's ``supporting_references`` list as the single
    ``"; "``-joined string shown in the CSV, the spec, and the ⓘ dialog."""
    return "; ".join(format_reference(ref) for ref in refs)


# -- Zebrafish / rodent anxiety & behaviour paradigms ------------------------

HALL_1934 = Reference(
    key="hall1934",
    text=(
        "Hall 1934, J. Comp. Psychol. 18(3):385-403 (emotional behavior in "
        "the rat: I. Defecation and urination as measures of individual "
        "differences in emotionality)"
    ),
    doi="10.1037/h0071444",
    author="Hall, C. S.",
    title=(
        "Emotional behavior in the rat. I. Defecation and urination as "
        "measures of individual differences in emotionality"
    ),
    year=1934,
    journal="Journal of Comparative Psychology",
    volume="18",
    pages="385-403",
)

SIMON_1994 = Reference(
    key="simon1994",
    text=(
        "Simon et al. 1994, Behav. Brain Res. 61(1):59-64 (thigmotaxis as "
        "an index of anxiety in mice)"
    ),
    doi="10.1016/0166-4328(94)90008-6",
    author="Simon, P. and Dupuis, R. and Costentin, J.",
    title=(
        "Thigmotaxis as an index of anxiety in mice. Influence of "
        "dopaminergic transmissions"
    ),
    year=1994,
    journal="Behavioural Brain Research",
    volume="61",
    pages="59-64",
)

SCHNORR_2012 = Reference(
    key="schnorr2012",
    text=(
        "Schnorr et al. 2012, Behav. Brain Res. 228(2):367-374 "
        "(thigmotaxis in larval zebrafish)"
    ),
    doi="10.1016/j.bbr.2011.12.016",
    author="Schnorr, S. J. and Steenbergen, P. J. and Richardson, M. K. and Champagne, D. L.",
    title="Measuring thigmotaxis in larval zebrafish",
    year=2012,
    journal="Behavioural Brain Research",
    volume="228",
    pages="367-374",
)

WALSH_CUMMINS_1976 = Reference(
    key="walsh1976",
    text=(
        "Walsh & Cummins 1976, Psychol. Bull. 83(3):482-504 (the open-field "
        "test: a critical review)"
    ),
    doi="10.1037/0033-2909.83.3.482",
    author="Walsh, R. N. and Cummins, R. A.",
    title="The open-field test: a critical review",
    year=1976,
    journal="Psychological Bulletin",
    volume="83",
    pages="482-504",
)

BOURIN_HASCOET_2003 = Reference(
    key="bourin2003",
    text=(
        "Bourin & Hascoet 2003, Eur. J. Pharmacol. 463(1-3):55-65 (the "
        "mouse light/dark box test)"
    ),
    doi="10.1016/S0014-2999(03)01274-3",
    author="Bourin, M. and Hascoet, M.",
    title="The mouse light/dark box test",
    year=2003,
    journal="European Journal of Pharmacology",
    volume="463",
    pages="55-65",
)

CACHAT_2010 = Reference(
    key="cachat2010",
    text=(
        "Cachat et al. 2010, Nat. Protoc. 5(11):1786-1799 (measuring "
        "behavioral and endocrine responses to novelty stress in adult "
        "zebrafish)"
    ),
    doi="10.1038/nprot.2010.140",
    author="Cachat, J. and Stewart, A. and Grossman, L. and others",
    title="Measuring behavioral and endocrine responses to novelty stress in adult zebrafish",
    year=2010,
    journal="Nature Protocols",
    volume="5",
    pages="1786-1799",
)

STEWART_2012 = Reference(
    key="stewart2012",
    text=(
        "Stewart et al. 2012, Neuropharmacology 62(1):135-143 (modeling "
        "anxiety using adult zebrafish: a conceptual review -- no "
        "operational threshold given)"
    ),
    doi="10.1016/j.neuropharm.2011.07.037",
    author="Stewart, A. and Gaikwad, S. and Kyzar, E. and others",
    title="Modeling anxiety using adult zebrafish: a conceptual review",
    year=2012,
    journal="Neuropharmacology",
    volume="62",
    pages="135-143",
)

KALUEFF_2013 = Reference(
    key="kalueff2013",
    text=(
        "Kalueff et al. 2013, Zebrafish 10(1):70-86 (towards a "
        "comprehensive catalog of zebrafish behavior 1.0 and beyond)"
    ),
    doi="10.1089/zeb.2012.0861",
    author="Kalueff, A. V. and Gebhardt, M. and Stewart, A. M. and others",
    title="Towards a comprehensive catalog of zebrafish behavior 1.0 and beyond",
    year=2013,
    journal="Zebrafish",
    volume="10",
    pages="70-86",
)

EGAN_2009 = Reference(
    key="egan2009",
    text=(
        "Egan et al. 2009, Behav. Brain Res. 205(1):38-44 (understanding "
        "behavioral and physiological phenotypes of stress and anxiety in "
        "zebrafish)"
    ),
    doi="10.1016/j.bbr.2009.06.022",
    author="Egan, R. J. and Bergner, C. L. and Hart, P. C. and others",
    title=(
        "Understanding behavioral and physiological phenotypes of stress "
        "and anxiety in zebrafish"
    ),
    year=2009,
    journal="Behavioural Brain Research",
    volume="205",
    pages="38-44",
)

MAXIMINO_2010 = Reference(
    key="maximino2010",
    text=(
        "Maximino et al. 2010, Behav. Brain Res. 214(2):157-171 "
        "(measuring anxiety in zebrafish: a critical review)"
    ),
    doi="10.1016/j.bbr.2010.05.031",
    author="Maximino, C. and de Brito, T. M. and Dias, C. A. G. de M. and others",
    title="Measuring anxiety in zebrafish: a critical review",
    year=2010,
    journal="Behavioural Brain Research",
    volume="214",
    pages="157-171",
)

# -- Path geometry / kinematics -----------------------------------------------

BENHAMOU_2004 = Reference(
    key="benhamou2004",
    text=(
        "Benhamou 2004, J. Theor. Biol. 229(2):209-220 (how to reliably "
        "estimate path tortuosity)"
    ),
    doi="10.1016/j.jtbi.2004.03.016",
    author="Benhamou, S.",
    title="How to reliably estimate the tortuosity of an animal's path",
    year=2004,
    journal="Journal of Theoretical Biology",
    volume="229",
    pages="209-220",
)

BENHAMOU_2013 = Reference(
    key="benhamou2013",
    text=(
        "Benhamou 2013, Ecol. Lett. 17(3):261-272 (of scales and "
        "stationarity in animal movements)"
    ),
    doi="10.1111/ele.12225",
    author="Benhamou, S.",
    title="Of scales and stationarity in animal movements",
    year=2013,
    journal="Ecology Letters",
    volume="17",
    pages="261-272",
)

KAREIVA_SHIGESADA_1983 = Reference(
    key="kareiva1983",
    text=(
        "Kareiva & Shigesada 1983, Oecologia 56(2-3):234-238 (analyzing "
        "insect movement as a correlated random walk)"
    ),
    doi="10.1007/BF00379695",
    author="Kareiva, P. M. and Shigesada, N.",
    title="Analyzing insect movement as a correlated random walk",
    year=1983,
    journal="Oecologia",
    volume="56",
    pages="234-238",
)

MWAFFO_2015 = Reference(
    key="mwaffo2015",
    text=(
        "Mwaffo et al. 2015, J. R. Soc. Interface 12(102):20140884 (a "
        "jump persistent turning walker to model zebrafish locomotion)"
    ),
    doi="10.1098/rsif.2014.0884",
    author="Mwaffo, V. and Anderson, R. P. and Butail, S. and Porfiri, M.",
    title="A jump persistent turning walker to model zebrafish locomotion",
    year=2015,
    journal="Journal of the Royal Society Interface",
    volume="12",
    pages="20140884",
)

MARQUES_2018 = Reference(
    key="marques2018",
    text=(
        "Marques et al. 2018, Curr. Biol. 28(2):181-195 (structure of the "
        "zebrafish locomotor repertoire revealed with unsupervised "
        "behavioral clustering; bouts segmented from tail shape at "
        "~700 fps -- not applicable to centroid-only tracking)"
    ),
    doi="10.1016/j.cub.2017.12.002",
    author="Marques, J. C. and Lackner, S. and Felix, R. and Orger, M. B.",
    title=(
        "Structure of the zebrafish locomotor repertoire revealed with "
        "unsupervised behavioral clustering"
    ),
    year=2018,
    journal="Current Biology",
    volume="28",
    pages="181-195",
)

SIBLY_1990 = Reference(
    key="sibly1990",
    text="Sibly et al. 1990, Anim. Behav. 39(1):63-69 (splitting behaviour into bouts)",
    doi="10.1016/S0003-3472(05)80726-2",
    author="Sibly, R. M. and Nott, H. M. R. and Fletcher, D. J.",
    title="Splitting behaviour into bouts",
    year=1990,
    journal="Animal Behaviour",
    volume="39",
    pages="63-69",
)

# -- Sequential / behavioural-event analysis ----------------------------------

MARTIN_BATESON_2007 = Reference(
    key="martinbateson2007",
    text=(
        "Martin & Bateson 2007, Measuring Behaviour: An Introductory "
        "Guide, 3rd ed. (Cambridge University Press)"
    ),
    doi="10.1017/CBO9780511810893",
    entry_type="book",
    author="Martin, P. and Bateson, P.",
    title="Measuring Behaviour: An Introductory Guide",
    year=2007,
    publisher="Cambridge University Press",
)

BAKEMAN_GOTTMAN_1997 = Reference(
    key="bakeman1997",
    text=(
        "Bakeman & Gottman 1997, Observing Interaction: An Introduction "
        "to Sequential Analysis, 2nd ed. (Cambridge University Press)"
    ),
    doi="10.1017/CBO9780511527685",
    entry_type="book",
    author="Bakeman, R. and Gottman, J. M.",
    title="Observing Interaction: An Introduction to Sequential Analysis",
    year=1997,
    publisher="Cambridge University Press",
)

# -- Space use / home range ----------------------------------------------------

MOHR_1947 = Reference(
    key="mohr1947",
    text=(
        "Mohr 1947, Am. Midl. Nat. 37(1):223-249 (table of equivalent "
        "populations of North American small mammals -- origin of the "
        "minimum convex polygon)"
    ),
    doi="10.2307/2421652",
    author="Mohr, C. O.",
    title="Table of equivalent populations of North American small mammals",
    year=1947,
    journal="American Midland Naturalist",
    volume="37",
    pages="223-249",
)

JACOBS_1974 = Reference(
    key="jacobs1974",
    text=(
        "Jacobs 1974, Oecologia 14(4):413-417 (quantitative measurement "
        "of food selection -- origin of the bias-corrected D electivity "
        "index)"
    ),
    doi="10.1007/BF00384581",
    author="Jacobs, J.",
    title="Quantitative measurement of food selection",
    year=1974,
    journal="Oecologia",
    volume="14",
    pages="413-417",
)

EILAM_GOLANI_1989 = Reference(
    key="eilam1989",
    text=(
        "Eilam & Golani 1989, Behav. Brain Res. 34(3):199-211 (home base "
        "behavior of rats exploring a novel environment)"
    ),
    doi="10.1016/S0166-4328(89)80102-0",
    author="Eilam, D. and Golani, I.",
    title="Home base behavior of rats (Rattus norvegicus) exploring a novel environment",
    year=1989,
    journal="Behavioural Brain Research",
    volume="34",
    pages="199-211",
)

FREUND_2013 = Reference(
    key="freund2013",
    text=(
        "Freund et al. 2013, Science 340(6133):756-759 (emergence of "
        "individuality in genetically identical mice)"
    ),
    doi="10.1126/science.1235294",
    author="Freund, J. and Brandmaier, A. M. and Lewejohann, L. and others",
    title="Emergence of individuality in genetically identical mice",
    year=2013,
    journal="Science",
    volume="340",
    pages="756-759",
)

# -- Circular statistics -------------------------------------------------------

BERENS_2009 = Reference(
    key="berens2009",
    text=(
        "Berens 2009, J. Stat. Softw. 31(10):1-21 (CircStat: a MATLAB "
        "toolbox for circular statistics)"
    ),
    doi="10.18637/jss.v031.i10",
    author="Berens, P.",
    title="CircStat: a MATLAB toolbox for circular statistics",
    year=2009,
    journal="Journal of Statistical Software",
    volume="31",
    pages="1-21",
)

# -- Group spacing, cohesion, collective motion ------------------------------

CLARK_EVANS_1954 = Reference(
    key="clarkevans1954",
    text=(
        "Clark & Evans 1954, Ecology 35(4):445-453 (distance to nearest "
        "neighbor as a measure of spatial relationships in populations)"
    ),
    doi="10.2307/1931034",
    author="Clark, P. J. and Evans, F. C.",
    title="Distance to nearest neighbor as a measure of spatial relationships in populations",
    year=1954,
    journal="Ecology",
    volume="35",
    pages="445-453",
)

PITCHER_1973 = Reference(
    key="pitcher1973",
    text=(
        "Pitcher 1973, Anim. Behav. 21(4):673-686 (the three-dimensional "
        "structure of schools in the minnow, Phoxinus phoxinus)"
    ),
    doi="10.1016/S0003-3472(73)80091-0",
    author="Pitcher, T. J.",
    title="The three-dimensional structure of schools in the minnow, Phoxinus phoxinus (L.)",
    year=1973,
    journal="Animal Behaviour",
    volume="21",
    pages="673-686",
)

KRAUSE_RUXTON_2002 = Reference(
    key="krauseruxton2002",
    text="Krause & Ruxton 2002, Living in Groups (Oxford University Press)",
    doi="10.1093/oso/9780198508175.001.0001",
    entry_type="book",
    author="Krause, J. and Ruxton, G. D.",
    title="Living in Groups",
    year=2002,
    publisher="Oxford University Press",
)

MILLER_GERLAI_2007 = Reference(
    key="millergerlai2007",
    text=(
        "Miller & Gerlai 2007, Behav. Brain Res. 184(2):157-166 "
        "(quantification of shoaling behaviour in zebrafish)"
    ),
    doi="10.1016/j.bbr.2007.07.007",
    author="Miller, N. and Gerlai, R.",
    title="Quantification of shoaling behaviour in zebrafish (Danio rerio)",
    year=2007,
    journal="Behavioural Brain Research",
    volume="184",
    pages="157-166",
)

DELCOURT_PONCIN_2012 = Reference(
    key="delcourtponcin2012",
    text=(
        "Delcourt & Poncin 2012, Rev. Fish Biol. Fish. 22(3):595-619 "
        "(shoals and schools: back to the heuristic definitions and "
        "quantitative references)"
    ),
    doi="10.1007/s11160-012-9260-z",
    author="Delcourt, J. and Poncin, P.",
    title="Shoals and schools: back to the heuristic definitions and quantitative references",
    year=2012,
    journal="Reviews in Fish Biology and Fisheries",
    volume="22",
    pages="595-619",
)

VICSEK_1995 = Reference(
    key="vicsek1995",
    text=(
        "Vicsek et al. 1995, Phys. Rev. Lett. 75(6):1226-1229 (novel type "
        "of phase transition in a system of self-driven particles -- "
        "origin of the polar order parameter)"
    ),
    doi="10.1103/PhysRevLett.75.1226",
    author="Vicsek, T. and Czirok, A. and Ben-Jacob, E. and others",
    title="Novel type of phase transition in a system of self-driven particles",
    year=1995,
    journal="Physical Review Letters",
    volume="75",
    pages="1226-1229",
)

COUZIN_2002 = Reference(
    key="couzin2002",
    text=(
        "Couzin et al. 2002, J. Theor. Biol. 218(1):1-11 (collective "
        "memory and spatial sorting in animal groups)"
    ),
    doi="10.1006/jtbi.2002.3065",
    author="Couzin, I. D. and Krause, J. and James, R. and others",
    title="Collective memory and spatial sorting in animal groups",
    year=2002,
    journal="Journal of Theoretical Biology",
    volume="218",
    pages="1-11",
)

TUNSTROM_2013 = Reference(
    key="tunstrom2013",
    text=(
        "Tunstrom et al. 2013, PLoS Comput. Biol. 9(2):e1002915 "
        "(collective states, multistability and transitional behavior "
        "in schooling fish)"
    ),
    doi="10.1371/journal.pcbi.1002915",
    author="Tunstrom, K. and Katz, Y. and Ioannou, C. C. and others",
    title="Collective states, multistability and transitional behavior in schooling fish",
    year=2013,
    journal="PLoS Computational Biology",
    volume="9",
    pages="e1002915",
)

BALLERINI_2008 = Reference(
    key="ballerini2008",
    text=(
        "Ballerini et al. 2008, Proc. Natl. Acad. Sci. 105(4):1232-1237 "
        "(interaction ruling animal collective behavior depends on "
        "topological rather than metric distance)"
    ),
    doi="10.1073/pnas.0711437105",
    author="Ballerini, M. and Cabibbo, N. and Candelier, R. and others",
    title=(
        "Interaction ruling animal collective behavior depends on "
        "topological rather than metric distance"
    ),
    year=2008,
    journal="Proceedings of the National Academy of Sciences",
    volume="105",
    pages="1232-1237",
)

# -- Tracking / multi-object-tracking evaluation ------------------------------

ROMERO_FERRERO_2019 = Reference(
    key="romeroferrero2019",
    text="Romero-Ferrero et al. 2019, Nat. Methods 16:179-182 (idtracker.ai)",
    doi="10.1038/s41592-018-0295-5",
    author="Romero-Ferrero, F. and Bergomi, M. G. and Hinz, R. C. and others",
    title=(
        "idtracker.ai: tracking all individuals in small or large "
        "collectives of unmarked animals"
    ),
    year=2019,
    journal="Nature Methods",
    volume="16",
    pages="179-182",
)

BERNARDIN_STIEFELHAGEN_2008 = Reference(
    key="bernardin2008",
    text=(
        "Bernardin & Stiefelhagen 2008, EURASIP J. Image Video Process. "
        "2008:246309 (evaluating multiple object tracking performance: "
        "the CLEAR MOT metrics)"
    ),
    doi="10.1155/2008/246309",
    author="Bernardin, K. and Stiefelhagen, R.",
    title="Evaluating multiple object tracking performance: the CLEAR MOT metrics",
    year=2008,
    journal="EURASIP Journal on Image and Video Processing",
    volume="2008",
    pages="246309",
)

BJORNERAAS_2010 = Reference(
    key="bjorneraas2010",
    text=(
        "Bjorneraas et al. 2010, J. Wildl. Manage. 74(6):1361-1366 "
        "(screening GPS location data for errors using animal movement "
        "characteristics)"
    ),
    doi="10.2193/2009-405",
    author="Bjorneraas, K. and Van Moorter, B. and Rolandsen, C. M. and Herfindal, I.",
    title=(
        "Screening global positioning system location data for errors "
        "using animal movement characteristics"
    ),
    year=2010,
    journal="Journal of Wildlife Management",
    volume="74",
    pages="1361-1366",
)
