import torch
import numpy as np
from torch_geometric.data import Data
from torch_geometric.utils import from_networkx
import numpy as np
from tqdm import tqdm
import random
import networkx as nx
from torch_geometric.nn import GCN
import sys
import matplotlib.pyplot as plt
from dataset import SISDataset
import os
from transforms import pyg_transform,spectral_transform,one_hot_transform,get_sequence,transformer_batch

def draw_and_save_graphs(sequence, frame_dir, sequence_idx):
    # Get positions for nodes in the first graph and use them for all graphs in the sequence
    pos = nx.spring_layout(sequence[0])
    
    for idx, graph in enumerate(sequence):
        plt.figure(figsize=(8, 6))
        
        # Draw susceptible nodes
        susceptible_non_neighbors = [node for node, data in graph.nodes(data=True) if data['state'] == 0]
        nx.draw_networkx_nodes(graph, pos, nodelist=susceptible_non_neighbors, node_color='blue', node_size=200)
        
        # Draw infected nodes
        infected_nodes = [node for node, data in graph.nodes(data=True) if data['state'] == 1]
        nx.draw_networkx_nodes(graph, pos, nodelist=infected_nodes, node_color='red', node_size=200)
        
        # Draw edges
        nx.draw_networkx_edges(graph, pos)
        
        # Save the frame
        frame_path = os.path.join(frame_dir, f'sequence_{sequence_idx}_frame_{idx}.png')
        plt.savefig(frame_path)
        plt.close()

def sis_dynamics_with_dynamic_edges(graph, beta, gamma, initial_infections, p_disconnect,time_steps=40):
    """
    Simulate the SIS model on a graph with changing edge structures.
    
    Parameters:
    - graph: initial graph with all nodes susceptible.
    - beta: probability that an edge between a susceptible node and an infected one spreads infection.
    - gamma: recovery probability.
    - initial_infections: number of initially infected nodes.
    - p_disconnect: maximum possible probability of a node disconnecting from an infected neighbor.
        Actual probability is p_disconnect * rho, where rho is the proportion of the population currently infected.
    
    Returns:
    - A sequence of graph states of length time_steps.
    """
    
    # Initialize states: 0 for Susceptible, 1 for Infected
    for node in graph.nodes():
        graph.nodes[node]['state'] = 0
    
    # Randomly select nodes for initial infection
    initial_infected_nodes = random.sample(list(graph.nodes()), initial_infections)
    for node in initial_infected_nodes:
        graph.nodes[node]['state'] = 1
    
    sequence = []
    
    for _ in range(time_steps):
        # Create a copy of the current graph to represent the next state
        next_graph = graph.copy()
        
        # Disconnect is more likely if there is a higher proportion of infected individuals
        rho = len([node for node in graph.nodes() if graph.nodes[node]['state'] == 1])/len(graph.nodes())
        for node in graph.nodes():
            if graph.nodes[node]['state'] == 0:  # If node is susceptible
                neighbors = list(graph.neighbors(node))
                infected_neighbors = [neighbor for neighbor in neighbors if graph.nodes[neighbor]['state'] == 1]
                # Disconnect from infected neighbors with a certain probability
                for infected_neighbor in infected_neighbors:
                    if random.random() < p_disconnect*rho:
                        next_graph.remove_edge(node, infected_neighbor)
                        
                        # Connect to a susceptible node once it disconnects from an infected node
                        susceptible_non_neighbors = [n for n in graph.nodes() if graph.nodes[n]['state'] == 0 and n != node and not graph.has_edge(node, n)]
                        if susceptible_non_neighbors:  # Check if there are any susceptible nodes to connect to
                            new_friend = random.choice(susceptible_non_neighbors)
                            next_graph.add_edge(node, new_friend)
                    # For every infected neighbor you could get sick
                    if random.random() < beta:
                        next_graph.nodes[node]['state'] = 1

                # # If the node has infected neighbors, it can get infected with probability beta
                # if len(infected_neighbors) > 0 and random.random() < beta:
                #     next_graph.nodes[node]['state'] = 1
                
            else:  # If node is infected
                # Node can recover with probability gamma
                if random.random() < gamma:
                    next_graph.nodes[node]['state'] = 0
        
        # Append the graph to the sequence
        sequence.append(next_graph)
        
        # Update the graph to the next state for the next iteration
        graph = next_graph
    
    return sequence



# if __name__ == "__main__":
#     infection_prob = 0.1
#     recovery_prob = 0.1
#     initial_infections = 5
#     prob_disconnect = .4
#     number_of_sequences = 20_000
    
#     sequences_to_save = []
#     for _ in tqdm(range(number_of_sequences)):
#         n = random.randint(20, 30)
#         G = nx.erdos_renyi_graph(n, 0.4)
#         sequence = sis_dynamics_with_dynamic_edges(G, infection_prob, recovery_prob, initial_infections, prob_disconnect)
#         pyg_sequence = [pyg_transform(graph) for graph in sequence]
#         pyg_sequence = [get_sequence(spectral_transform(one_hot_transform(graph))) for graph in pyg_sequence]
#         sequences_to_save.append(pyg_sequence)
#     # Save using PyTorch's save method
#     torch.save(sequences_to_save, 'sis_sequences.pt')


import sys

def main(array_id):
    # Calculate the range based on array_id
    start = (array_id - 1) * 1_000  # Assuming each job processes 1000 sequences
    end = array_id * 1_000
    infection_prob = 0.1
    recovery_prob = 0.1
    initial_infections = 5
    prob_disconnect = .4
    
    sequences_to_save = []
    sequences_to_save = []
    for _ in tqdm(range(start, end)):
        n = random.randint(20, 30)
        G = nx.erdos_renyi_graph(n, 0.4)
        sequence = sis_dynamics_with_dynamic_edges(G, infection_prob, recovery_prob, initial_infections, prob_disconnect)
        pyg_sequence = [pyg_transform(graph) for graph in sequence]
        pyg_sequence = [get_sequence(spectral_transform(one_hot_transform(graph))) for graph in pyg_sequence]
        sequences_to_save.append(pyg_sequence)

    # Save to a unique file based on array_id
    torch.save(sequences_to_save, f'small_dataset/sis_sequences_{array_id}.pt')

if __name__ == "__main__":
    array_id = int(sys.argv[1])  # Get SLURM array job index from command line
    main(array_id)
    # from torch_geometric.data import DataLoader

    # dataset = SISDataset(root='', sequences=sequences_to_save,transform=None)
    # loader = DataLoader(dataset, batch_size=3, shuffle=True)

    # model = GCN(21,32,2)
    # for batch in loader:
    #     # print(batch)
    #     a = torch.nn.Linear(21,5)
    #     b = torch.nn.Embedding(43,5)
    #     print(batch[0].state.shape)
    #     print(batch[0].x.shape)
    #     print(batch[0].eigenvalues.shape)
    #     print(batch[0].spectral_coords.shape)
    #     print(batch[0].ptr)
    #     print(len(batch))
    #     print(batch[0].discrete_data.shape)
    #     print(transformer_batch(batch[0],b,a)[0].shape)
    #     print(model(batch[0].x,batch[0].edge_index).shape)
    #     print(batch[0].batch)
    #     break



