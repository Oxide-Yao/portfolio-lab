"""Page selection and completion belong to different state dimensions."""
from hashlib import sha256
from html import escape
import json

PAGES = ('Overview', 'Risk analysis', 'Strategy comparison', 'Saved experiments')
STEPS = {'Overview': 'Configure portfolio', 'Risk analysis': 'Analyze risk',
         'Strategy comparison': 'Compare strategies', 'Saved experiments': 'Save experiment'}


def analysis_version(active):
    """A successful run (including its timestamp) has an immutable identity."""
    value = {'config': active['config'].to_dict(), 'calculated_at': active['calculated_at']}
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def update_progress(completed, page, dirty=False):
    """Viewing the applied results counts even while another draft is being edited."""
    completed = set(completed)
    if page in ('Risk analysis', 'Strategy comparison'):
        completed.add(page)
    return completed


def progress_html(page, completed, dirty=False):
    items = []
    for index, (key, label) in enumerate(STEPS.items()):
        active = key == page
        mark = '✓ ' if key in completed else ''
        aria = ' aria-current="step"' if active else ''
        # Keep the connector with the following whole step when wrapping.
        arrow = '<span class="workflow-arrow" aria-hidden="true">→</span>' if index else ''
        items.append('<span class="workflow-item">' + arrow +
                     f'<span class="workflow-step{" current" if active else ""}"'
                     f'{aria}>{mark}{escape(label)}</span></span>')
    return '<nav class="workflow" aria-label="Experiment progress">' + ''.join(items) + '</nav>'
