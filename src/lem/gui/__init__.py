from PySide6.QtWidgets import QStyleFactory


def fix_item_checkboxes(view):
    """Draw item-view checkboxes with Fusion instead of the native macOS style.

    Qt 6.11's macOS style only paints the first row's check indicator on
    macOS 27 (the rest are invisible, though clicks still register). Scoped to
    the view so the rest of the UI keeps the native look."""
    style = QStyleFactory.create("Fusion")
    style.setParent(view)  # QWidget.setStyle doesn't take ownership
    view.setStyle(style)
