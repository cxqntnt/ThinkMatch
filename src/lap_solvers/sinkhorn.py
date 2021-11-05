import mindspore
import mindspore.nn as nn
import mindspore.ops.operations as P
import mindspore.ops as ops
import mindspore.numpy as np
from mindspore.common.tensor import Tensor
import mindspore.context as context

context.set_context(device_target="GPU")

class Sinkhorn(nn.Cell):
    """
    Sinkhorn algorithm turns the input matrix into a bi-stochastic matrix.
    Parameter: maximum iterations max_iter
               a small number for numerical stability epsilon
    Input: input matrix s
    Output: bi-stochastic matrix s
    """
    def __init__(self, max_iter=10, tau=1., epsilon=1e-4, log_forward=True, batched_operation=False):
        super(Sinkhorn, self).__init__()
        self.max_iter = max_iter
        self.tau = tau
        self.epsilon = epsilon
        self.log_forward = log_forward
        if not log_forward:
            print('Warning: Sinkhorn algorithm without log forward is deprecated because log_forward is more stable.')
        self.batched_operation = batched_operation # batched operation may cause instability in backward computation,
                                                   # but will boost computation.

    def construct(self, *input, **kwinput):
        if self.log_forward:
            return self.forward_log(*input, **kwinput)
        else:
            return self.forward_ori(*input, **kwinput) # deprecated

    def forward_log(self, s, nrows=None, ncols=None, dummy_row=False, dtype=mindspore.float32):
        # computing sinkhorn with row/column normalization in the log space.
        if len(s.shape) == 2:
            s = P.ExpandDims()(s,0)
            matrix_input = True
        elif len(s.shape) == 3:
            matrix_input = False
        else:
            raise ValueError('input data shape not understood.')

        batch_size = s.shape[0]

        if s.shape[2] >= s.shape[1]:
            transposed = False
        else:
            perm = tuple(range(3, len(s.shape)))
            perm = (0, 2, 1) + perm
            s = P.Transpose()(s, perm)
            transposed = True

        if nrows is None:
            nrows = [s.shape[1] for _ in range(batch_size)]
        if ncols is None:
            ncols = [s.shape[2] for _ in range(batch_size)]

        # operations are performed on log_s
        s = s / self.tau

        if dummy_row:
            assert s.shape[2] >= s.shape[1]
            dummy_shape = list(s.shape)
            dummy_shape[1] = s.shape[2] - s.shape[1]
            ori_nrows = nrows
            nrows = ncols
            tmp = P.Zeros()(dummy_shape,mindspore.float32)-float('inf')
            np.full(dummy_shape, -float('inf'), np.float32)

            s = P.Concat(1)((s, np.full(dummy_shape, -float('inf'), np.float32)))
            for b in range(batch_size):
                s[b, ori_nrows[b]:nrows[b], :ncols[b]] = -100
                s[b, nrows[b]:, :] = -float('inf')
                s[b, :, ncols[b]:] = -float('inf')

        if self.batched_operation:
            log_s = s

            for i in range(self.max_iter):
                if i % 2 == 0:
                    log_sum = nn.ReduceLogSumExp(2, keep_dims=True)(log_s)
                    log_s = log_s - log_sum
                    log_s[np.isnan(log_s)] = -float('inf')
                else:
                    log_sum = nn.ReduceLogSumExp(1, keep_dims=True)(log_s)
                    log_s = log_s - log_sum
                    log_s[np.isnan(log_s)] = -float('inf')

                # ret_log_s[b, row_slice, col_slice] = log_s

            if dummy_row and dummy_shape[1] > 0:
                log_s = log_s[:, :-dummy_shape[1]]
                for b in range(batch_size):
                    log_s[b, ori_nrows[b]:nrows[b], :ncols[b]] = -float('inf')

            if matrix_input:
                log_s.squeeze(0)

            return P.Exp()(log_s)
        else:
            ret_log_s = np.full((batch_size, s.shape[1], s.shape[2]), -float('inf'), s.dtype)
            for b in range(batch_size):
                row_slice = slice(0, nrows[b])
                col_slice = slice(0, ncols[b])
                log_s = s[b, row_slice, col_slice]

                for i in range(self.max_iter):
                    if i % 2 == 0:
                        log_sum = nn.ReduceLogSumExp(1, keep_dims=True)(log_s)
                        if np.isinf(log_sum).any():
                            log_max = P.ReduceMax(keep_dims=True)(log_sum, 1)
                            for j in range(len(log_sum)):
                                if np.isinf(log_sum)[j]:
                                    log_sum[j] = log_max[j]
                        log_s = log_s - log_sum
                    else:
                        log_sum = nn.ReduceLogSumExp(0, keep_dims=True)(log_s)
                        if np.isinf(log_sum).any():
                            log_max = P.ReduceMax(keep_dims=True)(log_sum, 0)
                            for j in range(len(log_sum)):
                                if np.isinf(log_sum)[j]:
                                    log_sum[j] = log_max[j]
                        log_s = log_s - log_sum

                ret_log_s[b, row_slice, col_slice] = log_s

            if dummy_row:
                if dummy_shape[1] > 0:
                    ret_log_s = ret_log_s[:, :-dummy_shape[1]]
                for b in range(batch_size):
                    ret_log_s[b, ori_nrows[b]:nrows[b], :ncols[b]] = -float('inf')

            if transposed:
                perm = tuple(range(3, len(ret_log_s.shape)))
                perm = (0, 2, 1) + perm
                ret_log_s = P.Transpose()(ret_log_s, (0, 2, 1))
            if matrix_input:
                ret_log_s.squeeze(0)

            return P.Exp()(ret_log_s)

        # ret_log_s = torch.full((batch_size, s.shape[1], s.shape[2]), -float('inf'), device=s.device, dtype=s.dtype)

        # for b in range(batch_size):
        #    row_slice = slice(0, nrows[b])
        #    col_slice = slice(0, ncols[b])
        #    log_s = s[b, row_slice, col_slice]

    def forward_ori(self, s, nrows=None, ncols=None, dummy_row=False, dtype=mindspore.float32):
        # computing sinkhorn with row/column normalization.
        # This function is deprecated because forward_log is more numerically stable.
        if len(s.shape) == 2:
            s = P.ExpandDims()(s, 0)
            matrix_input = True
        elif len(s.shape) == 3:
            matrix_input = False
        else:
            raise ValueError('input data shape not understood.')

        batch_size = s.shape[0]

        #s = s.to(dtype=dtype)

        if nrows is None:
            nrows = [s.shape[1] for _ in range(batch_size)]
        if ncols is None:
            ncols = [s.shape[2] for _ in range(batch_size)]

        # tau scaling
        ret_s = np.zeros_like(s)
        for b, n in enumerate(nrows):
            ret_s[b, 0:n, 0:ncols[b]] = \
                P.Softmax(s[b, 0:n, 0:ncols[b]] / self.tau)
        s = ret_s

        # add dummy elements
        if dummy_row:
            dummy_shape = list(s.shape)
            dummy_shape[1] = s.shape[2] - s.shape[1]
            #s = torch.cat((s, torch.full(dummy_shape, self.epsilon * 10).to(s.device)), dim=1)
            #nrows = nrows + dummy_shape[1] # non in-place
            s = P.Concat(1)((s, np.full(dummy_shape, 0.0, np.float32)))
            ori_nrows = nrows
            nrows = ncols
            for b in range(batch_size):
                s[b, ori_nrows[b]:nrows[b], :ncols[b]] = self.epsilon

        row_norm_ones = np.zeros((batch_size, s.shape[1], s.shape[1]), s.dtype)  # size: row x row
        col_norm_ones = np.zeros((batch_size, s.shape[2], s.shape[2]), s.dtype)  # size: col x col
        for b in range(batch_size):
            row_slice = slice(0, nrows[b])
            col_slice = slice(0, ncols[b])
            row_norm_ones[b, row_slice, row_slice] = 1
            col_norm_ones[b, col_slice, col_slice] = 1

        s += self.epsilon

        for i in range(self.max_iter):
            if i % 2 == 0:
                # column norm
                #ones = torch.ones(batch_size, s.shape[1], s.shape[1], device=s.device)
                sum = P.ReduceSum()(P.Mul()(P.ExpandDims()(s, 3), P.ExpandDims()(col_norm_ones, 1)), axis=2)
            else:
                # row norm
                # ones = torch.ones(batch_size, s.shape[2], s.shape[2], device=s.device)
                sum = P.ReduceSum()(P.Mul()(P.ExpandDims()(row_norm_ones, 3), P.ExpandDims()(s, 1)), axis=2)

            tmp = np.zeros_like(s)
            for b in range(batch_size):
                row_slice = slice(0, nrows[b] if nrows is not None else s.shape[2])
                col_slice = slice(0, ncols[b] if ncols is not None else s.shape[1])
                tmp[b, row_slice, col_slice] = 1 / sum[b, row_slice, col_slice]
            s = s * tmp

        if dummy_row:
            if dummy_shape[1] > 0:
                s = s[:, :-dummy_shape[1]]
            for b in range(batch_size):
                s[b, ori_nrows[b]:nrows[b], :ncols[b]] = 0

        if matrix_input:
            s.squeeze(0)

        return s


class GumbelSinkhorn(nn.Cell):
    """
    GumbelSinkhorn Layer turns the input matrix into a bi-stochastic matrix.
    Parameter: maximum iterations max_iter
               a small number for numerical stability epsilon
    Input: input matrix s
    Output: bi-stochastic matrix s
    """
    def __init__(self, max_iter=10, tau=1., epsilon=1e-4, batched_operation=False):
        super(GumbelSinkhorn, self).__init__()
        self.sinkhorn = Sinkhorn(max_iter, tau, epsilon, batched_operation=batched_operation)

    def construct(self, s, nrows=None, ncols=None, sample_num=5, dummy_row=False, dtype=mindspore.float32):
        def sample_gumbel(t_like, eps=1e-20):
            """
            randomly sample standard gumbel variables
            """
            u = np.empty_like(t_like).uniform_()
            return -P.Log()(-P.Log()(u + eps) + eps)

        s_rep = np.repeat(s, sample_num, axis=0)
        s_rep = s_rep + sample_gumbel(s_rep)
        nrows_rep = np.repeat(nrows, sample_num, axis=0)
        ncols_rep = np.repeat(ncols, sample_num, axis=0)
        s_rep = self.sinkhorn(s_rep, nrows_rep, ncols_rep, dummy_row, dtype)
        #s_rep = torch.reshape(s_rep, (-1, sample_num, s_rep.shape[1], s_rep.shape[2]))
        return s_rep


if __name__ == '__main__':
    #bs = Sinkhorn(max_iter=8, epsilon=1e-4)
    #inp = Tensor([[[1., 0, 1.],
    #                     [1., 0, 3.],
    #                     [2., 0, 1.],
    #                     [4., 0, 2.]]] , mindspore.float32)
    #y = (3,4)
    #outp = bs(inp, y)

    #print(outp)
    #l = P.ReduceSum()(outp)
    #l.backward()
    #print(inp.grad * 1e10)

    grad_all = ops.GradOperation(get_all=True)
    bs = Sinkhorn(max_iter=8, epsilon=1e-4)
    inp = Tensor([[[1., 0, 1.],
                   [1., 0, 3.],
                   [2., 0, 1.],
                   [4., 0, 2.]]], mindspore.float32)
    y = Tensor([3,4], mindspore.int64)
    #y
    out = bs(inp)
    print(out)
    print(P.ReduceSum()(out))
    test = bs(inp)
    gr_fun = grad_all(bs)
    ret = gr_fun(inp)
    print(ret)


    #outp2 = Tensor([[0.1, 0.1, 1],
    #                      [2, 3, 4.]])

    #l = P.ReduceSum()(outp2)
    #l.backward()
    #print(outp2.grad)