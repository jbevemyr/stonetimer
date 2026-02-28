# Contributing to RockTimer

Thank you for your interest in contributing to RockTimer! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and constructive
- Help others learn and grow
- Focus on what's best for the community
- No harassment or inappropriate behavior

## How to Contribute

### Reporting Bugs

**Before submitting:**
1. Check existing issues
2. Test with latest version
3. Try troubleshooting steps in README

**When submitting:**
- Use a clear, descriptive title
- Describe expected vs. actual behavior
- Include steps to reproduce
- Add logs if relevant:
  ```bash
  sudo journalctl -u rocktimer-server -n 100
  ```
- Specify hardware (Pi model, sensors, display)
- Include config.yaml (remove sensitive data)

**Example:**
```
Title: Sensor triggers not detected on Pi Zero 2 W

Description:
Breaking the laser beam doesn't register on the server.
Local test (test_sensor.py) works, but UDP messages don't arrive.

Steps to reproduce:
1. Install sensor on Pi Zero with install_sensor.sh
2. Configure device_id: "tee"
3. Break laser beam
4. Check server logs - no trigger message

Environment:
- Pi Zero 2 W (Raspberry Pi OS Bookworm 64-bit)
- Server: Pi 4 (192.168.50.1)
- Network: Connected to rocktimer Wi-Fi
- Sensor logs: See attached
```

### Suggesting Features

**Good feature requests:**
- Solve a real problem
- Are clearly described
- Include use cases
- Consider implementation complexity

**Example:**
```
Title: Add CSV export for measurement history

Problem:
Coaches want to analyze stone times over multiple sessions,
but current system only shows in-memory history.

Proposed solution:
Add "Export CSV" button that downloads times as CSV file
with columns: timestamp, tee_to_hog_ms, hog_to_hog_ms, total_ms

Use cases:
- Track stone speed trends over practice sessions
- Compare different players
- Import into Excel/Google Sheets for analysis

Implementation notes:
- Add GET /api/export/csv endpoint
- Use Python csv module
- Download as attachment (Content-Disposition: attachment)
```

### Contributing Code

#### Setup Development Environment

```bash
# Fork the repo on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/rocktimer.git
cd rocktimer

# Create a branch
git checkout -b feature/your-feature-name

# Install dev dependencies
pip install -r requirements-server.txt
pip install -r requirements-sensor.txt

# Run in dev mode (no sudo needed if not using GPIO)
python server/main.py
```

#### Code Style

**Python:**
- Follow PEP 8
- Use type hints
- Add docstrings for classes and functions
- Keep functions small and focused
- Use descriptive variable names

**Good:**
```python
def calculate_split_time(start_ns: int, end_ns: int) -> float:
    """Calculate time difference in milliseconds.
    
    Args:
        start_ns: Start timestamp in nanoseconds
        end_ns: End timestamp in nanoseconds
        
    Returns:
        Time difference in milliseconds
    """
    return (end_ns - start_ns) / 1_000_000
```

**Bad:**
```python
def calc(a, b):  # No docstring, unclear names
    return (b - a) / 1000000  # Magic number
```

**JavaScript (web UI):**
- Use modern ES6+ syntax
- Add comments for complex logic
- Keep functions small
- Use meaningful names

**YAML/Config:**
- Add comments explaining each setting
- Use consistent indentation (2 spaces)
- Group related settings

#### Testing

**Before submitting:**

1. **Test locally:**
   ```bash
   # Server
   cd /opt/rocktimer
   sudo venv/bin/python server/main.py
   
   # Simulate triggers
   python tools/simulate_triggers.py --simulate --loop 5
   ```

2. **Test on real hardware** (if applicable):
   - Deploy to test Pi
   - Test with actual sensors
   - Verify timing accuracy

3. **Check logs for errors:**
   ```bash
   sudo journalctl -u rocktimer-server -n 100 --no-pager
   ```

4. **Test edge cases:**
   - Rapid double-triggers
   - Out-of-order triggers (hog before tee)
   - Network disconnection
   - Sensor timeout

#### Commit Messages

**Format:**
```
<type>: <short summary> (max 50 chars)

<optional longer description>

<optional footer>
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `style:` Formatting, no code change
- `refactor:` Code restructure, no behavior change
- `test:` Add or update tests
- `chore:` Build, dependencies, tooling

**Examples:**

Good:
```
feat: add CSV export for measurement history

Adds a new GET /api/export/csv endpoint that returns
measurements in CSV format for offline analysis.

Closes #42
```

```
fix: correct hog-to-hog time calculation

Previously used wrong timestamps for hog-to-hog split.
Now correctly uses hog_close_time_ns to hog_far_time_ns.

Fixes #38
```

Bad:
```
update stuff  # Too vague
```

```
fix bug  # No description
```

#### Pull Request Process

1. **Create PR:**
   - Use descriptive title
   - Reference related issues
   - Describe changes clearly
   - Add screenshots for UI changes

2. **PR checklist:**
   - [ ] Code follows style guidelines
   - [ ] Added/updated documentation
   - [ ] Tested locally
   - [ ] No breaking changes (or clearly marked)
   - [ ] Config.yaml.example updated if needed

3. **Review process:**
   - Maintainer will review
   - Address feedback
   - Make requested changes
   - PR will be merged or closed with explanation

**Example PR:**
```
Title: Add CSV export for measurement history

Description:
Implements CSV export feature requested in #42.

Changes:
- Add GET /api/export/csv endpoint
- Return measurements as CSV with headers
- Set Content-Disposition for auto-download
- Add "Export" button to web UI (next to "Clear")

Testing:
- Tested with 100 measurements
- Verified CSV format in Excel
- Tested with empty history (returns empty CSV)

Screenshots:
[screenshot of new Export button]

Closes #42
```

## Development Guidelines

### Architecture

**Read first:** [ARCHITECTURE.md](ARCHITECTURE.md)

**Key principles:**
- Server is single source of truth
- Sensors are stateless (just send triggers)
- WebSocket for real-time updates
- UDP for sensor triggers (low latency)
- State machine for measurement lifecycle

### Adding New Features

**Before coding:**
1. Open an issue to discuss
2. Get feedback on approach
3. Check if it fits project scope
4. Consider backward compatibility

**Feature categories:**

**1. Core timing features** (high priority):
- Improved accuracy
- New sensor types
- Timing algorithms

**2. UI improvements** (medium priority):
- Better visualization
- Accessibility
- Mobile optimization

**3. Hardware support** (medium priority):
- New displays
- Audio devices
- Alternative sensors

**4. Integrations** (low priority):
- Cloud sync
- External APIs
- Third-party services

### File Organization

```
server/
  main.py          # Server logic (don't make too large)
  static/
    index.html     # Web UI (keep self-contained)

sensor/
  sensor_daemon.py # Sensor logic (keep simple)

setup/
  *.sh             # Setup scripts (idempotent)

configs/
  *.yaml           # Config templates

tools/
  *.py             # Utilities (well-documented)
```

### Dependencies

**Adding new dependencies:**
- Must be available on Raspberry Pi OS
- Prefer apt packages over pip when possible
- Update requirements-*.txt
- Test on clean install

**Current dependencies:**

Server (Pi 4):
- fastapi, uvicorn (web server)
- websockets (real-time updates)
- pyyaml (config)
- gpiozero, lgpio (GPIO, via apt)

Sensor (Pi Zero):
- pyyaml (config)
- gpiozero, lgpio (GPIO, via apt)

### Documentation

**Always update:**
- README.md (user-facing features)
- QUICKSTART.md (if setup changes)
- ARCHITECTURE.md (if design changes)
- Code comments (complex logic)
- config.yaml.example (new settings)

### Versioning

**Semantic Versioning (SemVer):**
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

**Example:**
- `1.0.0` → `1.1.0`: Add CSV export (new feature)
- `1.1.0` → `1.1.1`: Fix timing bug (patch)
- `1.1.1` → `2.0.0`: Change config format (breaking)

## Community

### Getting Help

- **Documentation:** README, QUICKSTART, ARCHITECTURE
- **Issues:** Search existing issues
- **Discussions:** GitHub Discussions (if enabled)

### Helping Others

- Answer questions in issues
- Improve documentation
- Share your setup (photos, tips)
- Report bugs you encounter
- Test new features

## Special Contributions

### Documentation

**Always welcome:**
- Fix typos
- Clarify confusing sections
- Add diagrams
- Translate to other languages
- Add video tutorials

### Design

**Contributions:**
- UI mockups
- 3D-printable enclosures
- Wiring diagrams
- Logos / graphics

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Questions?

Open an issue or reach out to the maintainers.

---

**Thank you for contributing to RockTimer!** 🥌

