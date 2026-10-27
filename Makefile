BINDIR=/usr/bin
DESTDIR=
PROGNAME=ansible-qubes

.PHONY: test test-qubes

all: bin/*

clean:
	find -name '*~' -print0 | xargs -0 rm -fv
	rm -fv *.tar.gz *.rpm

test:
	python3 tests/probe.py
	python3 tests/master_probe.py
	python3 tests/json_fidelity_probe.py

# Runs the spec section 11.2 Qubes matrix (T8..T15) against a real
# domain:  make test-qubes VM=<qubes-vm-name>.  The domain must be
# disposable or expendable -- the tests intentionally leave orphans
# behind (tests/qubes_probe.py, spec section 9.2).
test-qubes:
	@test -n '$(VM)' || { echo 'usage: make test-qubes VM=<qubes-vm-name>'; exit 2; }
	QUBES_TEST_VM=$(VM) python3 tests/qubes_probe.py

dist: clean
	excludefrom= ; test -f .gitignore && excludefrom=--exclude-from=.gitignore ; DIR=$(PROGNAME)-`awk '/^Version:/ {print $$2}' $(PROGNAME).spec` && FILENAME=$$DIR.tar.gz && tar cvzf "$$FILENAME" --exclude="$$FILENAME" --exclude=.git --exclude=.gitignore $$excludefrom --transform="s|^|$$DIR/|S" --show-transformed *

rpm: dist
	T=`mktemp -d` && rpmbuild --define "_topdir $$T" -ta $(PROGNAME)-`awk '/^Version:/ {print $$2}' $(PROGNAME).spec`.tar.gz || { rm -rf "$$T"; exit 1; } && mv "$$T"/RPMS/*/* "$$T"/SRPMS/* . || { rm -rf "$$T"; exit 1; } && rm -rf "$$T"

srpm: dist
	T=`mktemp -d` && rpmbuild --define "_topdir $$T" -ts $(PROGNAME)-`awk '/^Version:/ {print $$2}' $(PROGNAME).spec`.tar.gz || { rm -rf "$$T"; exit 1; } && mv "$$T"/SRPMS/* . || { rm -rf "$$T"; exit 1; } && rm -rf "$$T"

install: all
	ls -la bin
	install -Dm 755 bin/* -t $(DESTDIR)/$(BINDIR)/
