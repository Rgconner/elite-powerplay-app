"""Visual Inspector test suite.

Each test module focuses on one layer:

* :mod:`test_threshold`       — pure threshold auto-adjust logic
* :mod:`test_state_store`     — SQLite state store CRUD + migrations
* :mod:`test_gpio_mock`       — mock GPIO backend edge / debounce behaviour
* :mod:`test_inspection`      — inspection engine on synthetic images
* :mod:`test_actions`         — action handler dispatch + emitter wiring
* :mod:`test_api`             — Flask test client smoke tests
"""
