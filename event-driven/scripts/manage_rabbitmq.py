#!/usr/bin/env python3
"""
RabbitMQ management utilities for the event-driven architecture.
This script helps monitor and manage RabbitMQ during load testing.

Usage:
  python3 manage_rabbitmq.py status              # Check RabbitMQ queue status
  python3 manage_rabbitmq.py purge               # Purge all messages from queues
  python3 manage_rabbitmq.py monitor             # Monitor queue status continuously
"""
import argparse
import os
import sys
import time
import json
import requests
from urllib.parse import quote_plus

# Default RabbitMQ management API settings
RABBIT_URL = os.environ.get('RABBIT_MANAGEMENT_URL', 'http://localhost:15672/api')
RABBIT_USER = os.environ.get('RABBIT_USER', 'guest')
RABBIT_PASS = os.environ.get('RABBIT_PASS', 'guest')
RABBIT_VHOST = os.environ.get('RABBIT_VHOST', '%2F')  # Default vhost is '/' URL encoded
QUEUES = ['grayscale', 'grayscale_processed']

def get_auth():
    """Return basic auth tuple for RabbitMQ API"""
    return (RABBIT_USER, RABBIT_PASS)

def check_queue_status(queue_name):
    """Get status information for a specific queue"""
    try:
        url = f"{RABBIT_URL}/queues/{RABBIT_VHOST}/{queue_name}"
        response = requests.get(url, auth=get_auth(), timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'name': queue_name,
                'messages': data.get('messages', 0),
                'consumers': data.get('consumers', 0),
                'messages_ready': data.get('messages_ready', 0),
                'messages_unacknowledged': data.get('messages_unacknowledged', 0),
                'state': data.get('state', 'unknown')
            }
        else:
            print(f"Error fetching queue {queue_name}: {response.status_code}")
            return {'name': queue_name, 'error': f"HTTP {response.status_code}"}
    
    except Exception as e:
        print(f"Error connecting to RabbitMQ: {e}")
        return {'name': queue_name, 'error': str(e)}

def purge_queue(queue_name):
    """Purge all messages from a queue"""
    try:
        url = f"{RABBIT_URL}/queues/{RABBIT_VHOST}/{queue_name}/contents"
        response = requests.delete(url, auth=get_auth(), timeout=10)
        
        if response.status_code == 204:
            print(f"Successfully purged queue: {queue_name}")
            return True
        else:
            print(f"Failed to purge queue {queue_name}: HTTP {response.status_code}")
            return False
    
    except Exception as e:
        print(f"Error purging queue {queue_name}: {e}")
        return False

def monitor_queues(interval=5, threshold=100):
    """Monitor queues continuously and alert if message count exceeds threshold"""
    print(f"Monitoring RabbitMQ queues (alert threshold: {threshold} messages)")
    print(f"Press Ctrl+C to stop monitoring")
    print("-" * 70)
    
    try:
        while True:
            statuses = [check_queue_status(q) for q in QUEUES]
            
            print(f"\033[H\033[J")  # Clear terminal
            print(f"RabbitMQ Queue Status - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 70)
            
            alert = False
            for status in statuses:
                message_count = status.get('messages', 0)
                ready = status.get('messages_ready', 0)
                unack = status.get('messages_unacknowledged', 0)
                
                status_color = "\033[92m"  # Green
                if message_count > threshold:
                    status_color = "\033[91m"  # Red
                    alert = True
                elif message_count > threshold // 2:
                    status_color = "\033[93m"  # Yellow
                
                print(f"Queue: {status['name']}")
                print(f"  Messages: {status_color}{message_count}\033[0m (Ready: {ready}, Unacked: {unack})")
                print(f"  Consumers: {status.get('consumers', 0)}")
                print(f"  State: {status.get('state', 'unknown')}")
                
                if 'error' in status:
                    print(f"  \033[91mERROR: {status['error']}\033[0m")
                    
                print("-" * 70)
            
            if alert:
                print("\033[91mALERT: Message threshold exceeded!\033[0m")
                print("Consider purging queues with: python3 manage_rabbitmq.py purge")
            
            # Show instructions
            print("\nCommands:")
            print("  p: Purge all queues")
            print("  q: Quit monitoring")
            
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")

def main():
    parser = argparse.ArgumentParser(description='RabbitMQ Management Utility')
    parser.add_argument('action', choices=['status', 'purge', 'monitor'], 
                        help='Action to perform')
    parser.add_argument('--interval', type=int, default=5,
                        help='Monitoring interval in seconds')
    parser.add_argument('--threshold', type=int, default=100,
                        help='Alert threshold for queue message count')
    
    args = parser.parse_args()
    
    if args.action == 'status':
        print("RabbitMQ Queue Status:")
        for queue in QUEUES:
            status = check_queue_status(queue)
            print(f"Queue: {status['name']}")
            if 'error' in status:
                print(f"  Error: {status['error']}")
            else:
                print(f"  Messages: {status.get('messages', 0)}")
                print(f"  Consumers: {status.get('consumers', 0)}")
                print(f"  State: {status.get('state', 'unknown')}")
    
    elif args.action == 'purge':
        print("Purging all queues...")
        for queue in QUEUES:
            purge_queue(queue)
    
    elif args.action == 'monitor':
        monitor_queues(args.interval, args.threshold)

if __name__ == "__main__":
    main()
