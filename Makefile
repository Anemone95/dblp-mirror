WORKFLOW_NAME=dblp-search
WORKFLOW_DIR=alfredworkflow/workflow5
OUTPUT_FILE=alfredworkflow/$(WORKFLOW_NAME).alfredworkflow

.PHONY: all workflow clean install server update

all: workflow

server:
	python3 run_server.py --host 0.0.0.0 --port 8765

update:
	python3 client.py pull

workflow: $(OUTPUT_FILE)

$(OUTPUT_FILE):
	ln -sf ../../settings.py $(WORKFLOW_DIR)/settings.py
	cd $(WORKFLOW_DIR) && zip -r ../$(WORKFLOW_NAME).alfredworkflow . -x '*/__pycache__/*' '__pycache__/*' '*.pyc'
	@echo "✅ 打包完成：$(OUTPUT_FILE)"

clean:
	rm -f $(OUTPUT_FILE)
	@echo "🧹 清理完成"

install: $(OUTPUT_FILE)
	open $(OUTPUT_FILE)
	@echo "🚀 正在安装到 Alfred..."
