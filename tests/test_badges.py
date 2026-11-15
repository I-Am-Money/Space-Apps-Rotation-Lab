# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""The shared provenance badge is a public interface across feature pages."""
import pytest
from ui.components import badge


@pytest.mark.parametrize('kind,label', [
    ('observed', 'Observed'), ('Estimated', 'Estimated'), ('modeled', 'Estimated'),
    ('your_input', 'Your input'), ('local', 'Your input'), ('Your input', 'Your input'),
    ('assumption', 'Assumption'), ('example', 'EXAMPLE DATA'), ('placeholder', 'EXAMPLE DATA'),
    ('EXAMPLE DATA', 'EXAMPLE DATA'),
])
def test_public_badge_labels(kind, label):
    assert '>' + label + '</span>' in badge(kind)


def test_example_is_red_without_theme_and_unknown_values_are_safe():
    assert 'color:#991b1b' in badge('example')
    assert '<script>' not in badge('<script>')
    assert '>Assumption</span>' in badge(None)
