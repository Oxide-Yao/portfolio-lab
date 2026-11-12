"""Small, explicit UI workflow state; it does not calculate investment results."""
from html import escape

PAGES = ('Overview', 'Risk analysis', 'Strategy comparison', 'Saved experiments')
STEPS = {'Overview': 'Configure portfolio', 'Risk analysis': 'Analyze risk',
         'Strategy comparison': 'Compare strategies', 'Saved experiments': 'Save experiment'}


def update_progress(completed, page, dirty, changed=False):
    """Draft edits invalidate progress; viewing pages never applies a draft."""
    completed = set() if changed else set(completed)
    if not dirty and page in ('Risk analysis', 'Strategy comparison'):
        completed.add(page)
    return completed


def progress_html(page, completed, dirty):
    current = 'Overview' if dirty else page
    items = []
    for key, label in STEPS.items():
        active = key == current
        mark = '✓ ' if key in completed else ''
        aria = ' aria-current="step"' if active else ''
        items.append(f'<span class="workflow-step{" current" if active else ""}"'
                     f'{aria}>{mark}{escape(label)}</span>')
    return '<nav class="workflow" aria-label="Experiment progress">' + '<span class="workflow-arrow" aria-hidden="true">→</span>'.join(items) + '</nav>'
