#!/usr/bin/env python3

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, ConnectionPatch, Circle
import numpy as np

# Create figure with subplots for different storage architectures
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 12))

# Colors
primary_color = '#667eea'
secondary_color = '#764ba2'
success_color = '#28a745'
warning_color = '#ffc107'
info_color = '#17a2b8'
storage_color = '#ff6b6b'
lb_color = '#6f42c1'

def draw_architecture(ax, title, storage_type="centralized"):
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 12)
    ax.axis('off')
    
    # Title
    ax.text(7, 11.5, f'{title}', fontsize=16, fontweight='bold', ha='center')
    
    # Load Balancer Layer
    lb_box = FancyBboxPatch((5.5, 9.5), 3, 1, 
                           boxstyle="round,pad=0.1", 
                           facecolor=lb_color, 
                           edgecolor='black', 
                           alpha=0.8)
    ax.add_patch(lb_box)
    ax.text(7, 10, 'Nginx Load Balancer\n(Port: 8000)', 
            fontsize=9, ha='center', va='center', fontweight='bold', color='white')
    
    # Frontend Layer
    frontend_box = FancyBboxPatch((0.5, 8), 3, 1, 
                                 boxstyle="round,pad=0.1", 
                                 facecolor=info_color, 
                                 edgecolor='black', 
                                 alpha=0.8)
    ax.add_patch(frontend_box)
    ax.text(2, 8.5, 'Frontend Gateway\n(Device Adaptive)', 
            fontsize=9, ha='center', va='center', fontweight='bold', color='white')
    
    # API Gateway Instances (Scalable)
    gateway_positions = [(4.5, 8), (6.5, 8), (8.5, 8)]
    for i, pos in enumerate(gateway_positions):
        alpha = 0.8 if i == 0 else 0.6
        linestyle = '-' if i == 0 else '--'
        
        gateway_box = FancyBboxPatch(pos, 1.8, 1, 
                                    boxstyle="round,pad=0.1", 
                                    facecolor=primary_color, 
                                    edgecolor='black', 
                                    alpha=alpha,
                                    linestyle=linestyle)
        ax.add_patch(gateway_box)
        label = 'API Gateway\n(Primary)' if i == 0 else f'API Gateway\n(Scale {i+1})'
        ax.text(pos[0] + 0.9, pos[1] + 0.5, label, 
                fontsize=8, ha='center', va='center', fontweight='bold', color='white')
    
    # Service Scaler
    scaler_box = FancyBboxPatch((10.5, 8), 3, 1, 
                               boxstyle="round,pad=0.1", 
                               facecolor=warning_color, 
                               edgecolor='black', 
                               alpha=0.8)
    ax.add_patch(scaler_box)
    ax.text(12, 8.5, 'Service Scaler\n(Gateway + Services)', 
            fontsize=9, ha='center', va='center', fontweight='bold', color='black')
    
    # RabbitMQ
    rabbitmq_box = FancyBboxPatch((5.5, 6), 3, 1, 
                                 boxstyle="round,pad=0.1", 
                                 facecolor=secondary_color, 
                                 edgecolor='black', 
                                 alpha=0.8)
    ax.add_patch(rabbitmq_box)
    ax.text(7, 6.5, 'RabbitMQ\n(Message Queue)', 
            fontsize=9, ha='center', va='center', fontweight='bold', color='white')
    
    # Processing Services
    service_positions = [(1.5, 4), (4, 4), (7, 4), (9.5, 4), (12, 4)]
    service_labels = ['Grayscale\n(Primary)', 'Grayscale\n(Scale 2)', 'Future\nService', 'Processing\n(Scale 3)', 'AI Service\n(Future)']
    
    for i, (pos, label) in enumerate(zip(service_positions, service_labels)):
        alpha = 0.8 if i in [0, 2] else 0.6
        linestyle = '-' if i in [0, 2] else '--'
        color = success_color if i < 4 else '#17a2b8'
        
        service_box = FancyBboxPatch(pos, 2, 1, 
                                   boxstyle="round,pad=0.1", 
                                   facecolor=color, 
                                   edgecolor='black', 
                                   alpha=alpha,
                                   linestyle=linestyle)
        ax.add_patch(service_box)
        ax.text(pos[0] + 1, pos[1] + 0.5, label, 
                fontsize=8, ha='center', va='center', fontweight='bold', color='white')
    
    # Storage Layer
    if storage_type == "centralized":
        # Centralized Storage
        minio_box = FancyBboxPatch((5.5, 2), 3, 1, 
                                  boxstyle="round,pad=0.1", 
                                  facecolor=storage_color, 
                                  edgecolor='black', 
                                  alpha=0.8)
        ax.add_patch(minio_box)
        ax.text(7, 2.5, 'MinIO Storage\n(Centralized)', 
                fontsize=9, ha='center', va='center', fontweight='bold', color='white')
        
        # Storage connections
        for pos in service_positions:
            arrow = ConnectionPatch((pos[0] + 1, pos[1]), (7, 3), "data", "data",
                                  arrowstyle="<->", shrinkA=5, shrinkB=5, 
                                  mutation_scale=15, fc=storage_color, ec=storage_color, lw=1.5)
            ax.add_patch(arrow)
    
    else:
        # Distributed Storage
        storage_positions = [(2.5, 2), (5.5, 2), (8.5, 2), (11.5, 2)]
        storage_labels = ['MinIO\n(Service 1)', 'MinIO\n(Service 2)', 'MinIO\n(Service 3)', 'MinIO\n(Global)']
        
        for i, (pos, label) in enumerate(zip(storage_positions, storage_labels)):
            storage_box = FancyBboxPatch(pos, 2, 1, 
                                        boxstyle="round,pad=0.1", 
                                        facecolor=storage_color, 
                                        edgecolor='black', 
                                        alpha=0.8 if i < 3 else 0.6)
            ax.add_patch(storage_box)
            ax.text(pos[0] + 1, pos[1] + 0.5, label, 
                    fontsize=8, ha='center', va='center', fontweight='bold', color='white')
        
        # Storage sync connections
        for i in range(len(storage_positions) - 1):
            pos1 = storage_positions[i]
            pos2 = storage_positions[i + 1]
            arrow = ConnectionPatch((pos1[0] + 2, pos1[1] + 0.5), (pos2[0], pos2[1] + 0.5), "data", "data",
                                  arrowstyle="<->", shrinkA=5, shrinkB=5, 
                                  mutation_scale=12, fc='orange', ec='orange', lw=1, linestyle='dashed')
            ax.add_patch(arrow)
        
        # Service to storage connections
        for i, service_pos in enumerate(service_positions[:4]):
            if i < len(storage_positions):
                storage_pos = storage_positions[i]
                arrow = ConnectionPatch((service_pos[0] + 1, service_pos[1]), (storage_pos[0] + 1, storage_pos[1] + 1), 
                                      "data", "data", arrowstyle="<->", shrinkA=5, shrinkB=5, 
                                      mutation_scale=15, fc=storage_color, ec=storage_color, lw=1.5)
                ax.add_patch(arrow)
    
    # Load Balancer to Gateways
    for i, pos in enumerate(gateway_positions):
        alpha = 0.8 if i == 0 else 0.4
        arrow = ConnectionPatch((7, 9.5), (pos[0] + 0.9, pos[1] + 1), "data", "data",
                              arrowstyle="->", shrinkA=5, shrinkB=5, 
                              mutation_scale=15, fc=lb_color, ec=lb_color, lw=2, alpha=alpha)
        ax.add_patch(arrow)
    
    # Frontend to Load Balancer
    arrow = ConnectionPatch((3.5, 8.5), (5.5, 10), "data", "data",
                          arrowstyle="->", shrinkA=5, shrinkB=5, 
                          mutation_scale=20, fc=info_color, ec=info_color, lw=2)
    ax.add_patch(arrow)
    
    # Gateways to RabbitMQ
    arrow = ConnectionPatch((6.4, 8), (7, 7), "data", "data",
                          arrowstyle="->", shrinkA=5, shrinkB=5, 
                          mutation_scale=20, fc=primary_color, ec=primary_color, lw=2)
    ax.add_patch(arrow)
    
    # RabbitMQ to Services
    for pos in service_positions:
        arrow = ConnectionPatch((7, 6), (pos[0] + 1, pos[1] + 1), "data", "data",
                              arrowstyle="->", shrinkA=5, shrinkB=5, 
                              mutation_scale=15, fc=secondary_color, ec=secondary_color, lw=1.5)
        ax.add_patch(arrow)
    
    # Scaler monitoring
    scaler_arrow1 = ConnectionPatch((11.5, 8.5), (8.5, 6.5), "data", "data",
                                   arrowstyle="->", shrinkA=5, shrinkB=5, 
                                   mutation_scale=12, fc=warning_color, ec=warning_color, lw=1.5,
                                   linestyle='dashed')
    ax.add_patch(scaler_arrow1)
    
    scaler_arrow2 = ConnectionPatch((12, 8), (8.5, 8.5), "data", "data",
                                   arrowstyle="->", shrinkA=5, shrinkB=5, 
                                   mutation_scale=12, fc=warning_color, ec=warning_color, lw=1.5,
                                   linestyle='dashed')
    ax.add_patch(scaler_arrow2)
    
    # Legend
    legend_y = 0.5
    if storage_type == "centralized":
        ax.text(1, legend_y, "✅ Centralized Storage\n• Single MinIO instance\n• Simpler architecture\n• Single point of failure\n• Easier backup/restore", 
                fontsize=8, ha='left', va='center', bbox=dict(boxstyle="round,pad=0.3", facecolor='lightgreen', alpha=0.7))
    else:
        ax.text(0.5, legend_y, "✅ Distributed Storage\n• Multiple MinIO instances\n• Service-specific storage\n• Data synchronization\n• Higher availability\n• Better performance", 
                fontsize=8, ha='left', va='center', bbox=dict(boxstyle="round,pad=0.3", facecolor='lightblue', alpha=0.7))
    
    # Scaling info
    scaling_info = """🔄 Auto-Scaling Features:
• API Gateway: Load-based scaling (1-3 instances)
• Processing Services: Queue-based scaling (1-5 instances)
• Load Balancer: Nginx with dynamic upstream
• Service Scaler: Monitors both types"""
    
    ax.text(10, 0.5, scaling_info, fontsize=8, ha='left', va='center', 
            bbox=dict(boxstyle="round,pad=0.3", facecolor='lightyellow', alpha=0.7))

# Draw both architectures
draw_architecture(ax1, "Scalable Architecture - Centralized Storage", "centralized")
draw_architecture(ax2, "Scalable Architecture - Distributed Storage", "distributed")

# Main title
fig.suptitle('🏗️ Scalable API Gateway Event-Driven Architecture\nWith Storage Options', 
             fontsize=20, fontweight='bold', y=0.95)

# Add architectural comparison
fig.text(0.5, 0.02, 
         """🔍 Architecture Comparison: Both architectures feature scalable API Gateway with Nginx load balancing and auto-scaling capabilities.
         Left: Centralized storage (simpler, single point of failure) | Right: Distributed storage (more complex, higher availability)""", 
         ha='center', fontsize=10, style='italic')

plt.tight_layout()
plt.subplots_adjust(top=0.88, bottom=0.12)
plt.savefig('/home/giacomopedemonte/OpenMp-Parallel-Computing/event-driven/scalable_architecture_diagram.png', 
            dpi=300, bbox_inches='tight', facecolor='white')
plt.close()

print("Scalable architecture diagram saved as scalable_architecture_diagram.png")
