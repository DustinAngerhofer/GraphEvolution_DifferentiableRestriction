import torch
import torch.nn as nn
from torch.nn import TransformerEncoderLayer as Layer
from torch.nn import TransformerEncoder as Encoder
from torch.nn import Transformer
import lightning as L

from utils import positional_embedding, draw_graph
import torch.nn.functional as F
NO_EDGE = torch.Tensor([0]).long()
NEW_EDGE = torch.Tensor([1]).long()
NEW_NODE = torch.Tensor([2]).long()
EOS_TOKEN = torch.Tensor([3]).long()
SOS_TOKEN = torch.Tensor([4]).long()

class GraphEncoder(nn.Module):
    def __init__(self, num_states, d_model, num_layers):
        super().__init__()
        self.d_model = d_model
        self.cls = torch.Tensor([num_states]).long()
        encoder_layer = Layer(d_model = d_model, nhead = 8, batch_first=True)
        self.encoder = Encoder(encoder_layer,num_layers=num_layers)
        self.emb = nn.Embedding(num_states+1,d_model)
        self.position_encoding_embedder = nn.Linear(8,d_model)
        self.cls_encoding_embedder = nn.Sequential(nn.Linear(8,d_model),
                                                   nn.ReLU(),
                                                   nn.Linear(d_model,d_model))
        self.device="cuda"

    def forward(self, A, x):
        A = A+torch.eye(A.shape[-1]).to(self.device)
        embeddings = self.emb(x)
        positional_encodings, eigenvalues = self.positional_encoding(A)
        positional_encodings = self.position_encoding_embedder(positional_encodings)
        eigenvalues = self.cls_encoding_embedder(eigenvalues)
        embeddings += positional_encodings
        cls_token = (self.emb(self.cls.to(A.device))).repeat(A.shape[0],1,1)+ eigenvalues.unsqueeze(1)
        embeddings = torch.hstack((embeddings,cls_token))
        A= torch.dstack((A,torch.ones(A.shape[0],A.shape[-1],1).to(A.device)))
        A= torch.hstack((A,torch.ones(A.shape[0],1,A.shape[-1]).to(A.device)))
        adj_mask = self.adj_mask(A)
        output = self.encoder(embeddings, mask = adj_mask.repeat(8,1,1))
        cls_output = output[:,-1]# get the last elt we put in

        return cls_output


        
    def adj_mask(self, A):
    # Create a mask of -inf and zeros
        mask_values = torch.full((A.shape[-1], A.shape[-1]), float('-inf'), device=self.device)
        zeros = torch.zeros((A.shape[-1], A.shape[-1]), device=self.device)

        # Use where to set entries corresponding to zeros in A to -inf and non-zeros to 0
        mask = torch.where(A == 0, mask_values, zeros)

        return mask
    def positional_encoding(self,A, pos_enc_dim = 8):
        """
            Graph positional encoding v/ Laplacian eigenvectors
        """

        # Laplacian
        D=torch.diag_embed(A.sum(dim=-1)**(-.5))
        # print(A)
        # print(A.sum(dim=-1))
        # print(A.shape,D.shape)
        L = torch.eye(A.shape[-1]).to(self.device) - D @ A.float() @ D

        # print(L)
        # Eigenvectors with numpy
        eig_results = torch.linalg.eig(L)
    
        # Extract eigenvalues and eigenvectors
        EigVal = torch.real(eig_results.eigenvalues)
        EigVec = torch.real(eig_results.eigenvectors)

        # Sort eigenvalues in ascending order and get the indices
        sorted_indices = torch.argsort(EigVal, dim=-1, descending=False)

        # Use the indices to rearrange the eigenvectors
        sorted_EigVal = torch.gather(EigVal, -1, sorted_indices)
        sorted_EigVec = torch.gather(EigVec, -1, sorted_indices.unsqueeze(-1).expand(EigVec.shape))
        symmetric = sorted_EigVec.permute(0,2,1)
    
        return symmetric[:, :, 1:pos_enc_dim+1].float(), sorted_EigVal[:,1:pos_enc_dim+1]

class GraphAutoEncoder(L.LightningModule):
    def __init__(self, d_model,d_data,dataset,num_layers):
        super().__init__()

        self.embedder = nn.Embedding(5,d_model)
        self.expander = nn.Linear(d_data,d_model)
        self.decode_data = nn.Sequential(
                                        nn.Linear(d_model,d_model),
                                        nn.ReLU(),
                                        nn.Linear(d_model,d_data)
                                        )
        self.decode_edge = nn.Sequential(
                                        nn.Linear(d_model,d_model),
                                         nn.ReLU(),
                                         nn.Linear(d_model,5)
                                         )
        self.embedding_size = d_model
        self.encoder = GraphEncoder(d_data,d_model,num_layers)
        encoder_layer = Layer(d_model=d_model,nhead=4,batch_first=True)
        self.decoder = Encoder(encoder_layer=encoder_layer,num_layers = num_layers)
        self.criterion_soft = nn.MSELoss()
        self.criterion_hard = nn.CrossEntropyLoss()
        self.dataset = dataset
        self.A, self.b = self.dataset[0]

    def forward(self,sequence):
        position_emb = positional_embedding(sequence.shape[-2],self.embedding_size)
        return self.decoder(sequence+ position_emb.to(self.device),Transformer.generate_square_subsequent_mask(sequence.shape[-2]).to(self.device))
    
    def configure_optimizers(self):
        return torch.optim.AdamW(lr=4e-6,params = self.parameters())
    
    def training_step(self, batch, batch_idx):
        A, x = batch
        latent_embeddings = self.encoder(A,torch.argmax(x,dim=-1))

        sequence,hard_targets, soft_targets,mask = self.get_sequence_batched(A,x,self.embedder,self.expander,latent_embeddings)
        input_seq = sequence[:,:-1]
        # target_seq = sequence[:,1:]
        output_seq = self(input_seq)
        output_soft = self.decode_data(output_seq[:,mask])
        output_hard = self.decode_edge(output_seq[:,~mask])
        loss_soft = self.criterion_soft(output_soft,soft_targets)
        loss_hard = self.criterion_hard(output_hard.reshape(-1,5),hard_targets.reshape(-1))
        loss = loss_hard + loss_soft
        if (self.trainer.is_last_batch):
            print(loss_hard,loss_soft)
            print(loss.item())
        self.log("hard_loss", loss_hard)
        self.log("soft_loss", loss_soft)
        return loss

    def on_train_epoch_start(self):
        with torch.no_grad():
            print("encoder:")
            # print(self.encoder(self.A.unsqueeze(0).to(self.device),torch.argmax(self.b.unsqueeze(0).to(self.device),dim=-1)))
            A, x = self.dataset[0]
            draw_graph(A.numpy(),torch.argmax(x,dim=-1).cpu().detach().numpy(),f"{self.current_epoch}")
            A = A.unsqueeze(0).to(self.device)
            x = x.unsqueeze(0).to(self.device)
            latent_representation = self.encoder(A,torch.argmax(x,dim=-1))
            
            

            sequence  = latent_representation.unsqueeze(1)#self.embedder(SOS_TOKEN.to(self.device)).unsqueeze(0).to(self.device)
            new_node_emb = self.embedder(NEW_NODE.to(self.device)).unsqueeze(0).to(self.device)
            new_edge = self.embedder(NEW_EDGE.to(self.device)).squeeze(0)
            no_edge = self.embedder(NO_EDGE.to(self.device)).squeeze(0)
            x = []
            A = torch.eye(9)
            for i in range(9):
                sequence = torch.hstack((sequence,new_node_emb))
                output = self(sequence)
                latent_representation = self.decode_data(output[0,-1,:]).round().float()
                x.append(latent_representation)
                # print(sequence.shape,self.expander(latent_representation).unsqueeze(0).unsqueeze(0).shape)
                sequence = torch.hstack((sequence,self.expander(latent_representation).unsqueeze(0).unsqueeze(0)))

                for j in range(i):
                    output = self(sequence)
                    edge = self.decode_edge(output[0,-1,:])
                    edge_probs =F.softmax(edge[:2],dim=-1)
                    choice = torch.multinomial(edge_probs,1)
                    
                    if choice == 1:
                        sequence = torch.hstack((sequence,new_edge.unsqueeze(0).unsqueeze(0)))
                        A[i,j] = 1
                    else:
                        sequence = torch.hstack((sequence,no_edge.unsqueeze(0).unsqueeze(0)))
                        A[i,j] = 0
            A = A + A.T
            x = torch.vstack(x)
            graph = A.numpy()
            # print(x)
            communities = torch.argmax(x,dim=-1).cpu().detach().numpy()
            draw_graph(graph,communities,f"{self.current_epoch}_reconstructed")


    def get_sequence_batched(self, A,x,emb,expander,latent_embeddings):
        batch_size = A.shape[0]
        num_nodes = A.shape[1]

        sos_emb = latent_embeddings#emb(SOS_TOKEN.to(self.device)).repeat(batch_size, 1).to(self.device)
        new_node_emb = emb(NEW_NODE.to(self.device)).repeat(batch_size,1).to(self.device)
        eos_emb = emb(EOS_TOKEN.to(self.device)).repeat(batch_size, 1).to(self.device)

        indices = []
        for j in range(1, num_nodes):
            for i in range(j):
                indices.append((i, j))
        row_indices, col_indices = zip(*indices)
        row_indices = torch.tensor(row_indices).long()
        col_indices = torch.tensor(col_indices).long()
        adj_values = A[:, row_indices, col_indices]        
        # A_masked = A+mask
        # adj_values = A[A_masked > -10].view(batch_size,-1)
        sequences = sos_emb.unsqueeze(1)
        start = 0
        end = 1
        hard_targets = SOS_TOKEN.repeat(batch_size,1,1)
        soft_targets = None
        soft_target_mask = torch.tensor([False])
        for i in range(num_nodes):
            sequences = torch.hstack((sequences,new_node_emb.unsqueeze(1)))
            hard_targets = torch.hstack((hard_targets,NEW_NODE.repeat(batch_size,1,1)))
            soft_target_mask = torch.cat([soft_target_mask,torch.tensor([False])])
            sequences = torch.hstack((sequences,expander(x[:,i,:].unsqueeze(1))))
            if soft_targets == None:
                soft_targets = x[:,i,:].unsqueeze(1)
            else:
                soft_targets = torch.hstack([soft_targets,x[:,i,:].unsqueeze(1)])
            soft_target_mask = torch.cat([soft_target_mask,torch.tensor([True])])
            if i > 0:
                sequences = torch.hstack((sequences,emb(adj_values[:,start:end])))
                soft_target_mask = torch.cat([soft_target_mask,torch.tensor([False]*(end-start))])
                hard_targets = torch.hstack((hard_targets,adj_values[:,start:end].cpu().unsqueeze(-1)))
                start = end
                end = end + i+1
        sequences = torch.hstack((sequences,eos_emb.unsqueeze(1)))
        hard_targets = torch.hstack((hard_targets,EOS_TOKEN.repeat(batch_size,1,1)))
        soft_target_mask = torch.cat([soft_target_mask,torch.tensor([False])])
        return sequences, hard_targets[:,1:].to(self.device), soft_targets.to(self.device), soft_target_mask[1:].to(self.device)
