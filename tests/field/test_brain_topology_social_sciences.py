from __future__ import annotations

from nouse.field.brain_topology import classify_domain


def test_sociology_and_economics_classify_to_parietal():
    assert classify_domain("sociologi") == "parietal"
    assert classify_domain("ekonomi") == "parietal"
    assert classify_domain("organisation") == "parietal"
    assert classify_domain("politik") == "parietal"
    assert classify_domain("samhälle") == "parietal"


def test_philosophy_classifies_to_prefrontal():
    assert classify_domain("filosofi") == "prefrontal"
    assert classify_domain("philosophy") == "prefrontal"


def test_pedagogy_classifies_to_hippocampus():
    assert classify_domain("pedagogik") == "hippocampus"
    assert classify_domain("didaktik") == "hippocampus"


def test_previously_classified_domains_unaffected():
    assert classify_domain("matematik") == "frontal"
    assert classify_domain("kreativitet") == "temporal_right"
    assert classify_domain("etik") == "amygdala"
    assert classify_domain("programmering") == "cerebellum"
