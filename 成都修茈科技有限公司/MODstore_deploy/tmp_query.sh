#!/bin/bash
docker exec modstore_deploy-api-1 env | grep -E 'MODSTORE_|FERNET|MASTER_KEY|LLM_KEY' | sort
