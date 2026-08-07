.PHONY: run dev docker test clean
run:
	./dev_mac.sh
dev:
	./dev_mac.sh
docker:
	docker compose up --build
test:
	PYTHONPATH=backend python -m unittest discover -s tests -v
clean:
	rm -rf .venv backend/data/finsight.db backend/data/uploads/* backend/data/results/*
