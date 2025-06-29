#!/bin/bash
# reset_services.sh - Script to gracefully reset the event-driven system services
# when they become overwhelmed or enter a bad state

# Set constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Event-Driven System Recovery Script${NC}"
echo "This script will help reset services that have crashed or are in a bad state."

# Function to check services status
check_services() {
  echo -e "\n${YELLOW}Checking service status...${NC}"
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ps
}

# Function to purge RabbitMQ queues
purge_rabbitmq() {
  echo -e "\n${YELLOW}Purging RabbitMQ queues...${NC}"
  "$SCRIPT_DIR/manage_rabbitmq.py" purge
}

# Function to restart specific services
restart_service() {
  local service=$1
  
  echo -e "\n${YELLOW}Restarting $service...${NC}"
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" restart "$service"
  
  # Wait for service to stabilize
  echo "Waiting for $service to stabilize..."
  sleep 5
}

# Main menu
show_menu() {
  echo -e "\n${GREEN}=== Event-Driven System Recovery Menu ===${NC}"
  echo "1. Check service status"
  echo "2. Purge RabbitMQ queues"
  echo "3. Restart RabbitMQ"
  echo "4. Restart grayscale service"
  echo "5. Restart frontend"
  echo "6. Restart entire system (ordered restart)"
  echo "7. Monitor RabbitMQ queues"
  echo "8. Exit"
  echo -ne "\nChoose an option [1-8]: "
}

restart_ordered() {
  echo -e "\n${YELLOW}Performing ordered restart of all services...${NC}"
  
  # First stop services in reverse order of dependency
  echo "Stopping frontend..."
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" stop frontend
  
  echo "Stopping grayscale service..."
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" stop grayscale
  
  # Purge queues while services are stopped
  echo "Purging RabbitMQ queues..."
  purge_rabbitmq
  
  # Restart RabbitMQ first to ensure clean state
  echo "Restarting RabbitMQ..."
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" restart rabbitmq
  
  # Wait for RabbitMQ to be ready
  echo "Waiting for RabbitMQ to stabilize..."
  sleep 10
  
  # Now start services in order
  echo "Starting grayscale service..."
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" start grayscale
  
  echo "Waiting for grayscale service to initialize..."
  sleep 5
  
  echo "Starting frontend..."
  docker-compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" start frontend
  
  echo -e "${GREEN}All services have been restarted in the correct order.${NC}"
}

# Main program loop
while true; do
  show_menu
  read -r choice
  
  case $choice in
    1) check_services ;;
    2) purge_rabbitmq ;;
    3) restart_service "rabbitmq" ;;
    4) restart_service "grayscale" ;;
    5) restart_service "frontend" ;;
    6) restart_ordered ;;
    7) "$SCRIPT_DIR/manage_rabbitmq.py" monitor ;;
    8) echo -e "${GREEN}Exiting.${NC}"; exit 0 ;;
    *) echo -e "${RED}Invalid option. Please try again.${NC}" ;;
  esac
  
  echo -e "\nPress Enter to continue..."
  read -r
done
