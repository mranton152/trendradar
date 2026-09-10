import pytest

from semantic.filter import technology_reason


@pytest.mark.parametrize(
    "label",
    [
        "neural networks",
        "quantum computing",
        "gene editing",
        "cancer immunotherapy",
        "covid-19 vaccine",
        "нейронные сети",
        "редактирование генома",
        "квантовые вычисления",
    ],
)
def test_technology_and_biomedical_methods_are_kept(label):
    assert technology_reason(label) is None


@pytest.mark.parametrize(
    "label",
    [
        "covid-19 pandemic",
        "breast cancer",
        "diabetes mellitus",
        "United States",
        "World Health Organization",
        "recent study",
        "",
    ],
)
def test_events_diseases_and_generic_labels_have_rejection_reason(label):
    assert technology_reason(label)


@pytest.mark.parametrize("label", ["artificial neural", "convolutional neural"])
def test_terminal_adjectives_are_explained_as_incomplete_terms(label):
    assert technology_reason(label) == "оборванный термин: конечный модификатор"


@pytest.mark.parametrize(
    "label", ["neural network", "convolutional neural network", "quantum computing"]
)
def test_complete_technology_terms_survive_terminal_modifier_check(label):
    assert technology_reason(label) is None
