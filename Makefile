install-hooks:
	chmod +x hooks/pre-commit
	ln -sf ../../hooks/pre-commit .git/hooks/pre-commit
	@echo "Pre-commit hook installed."
