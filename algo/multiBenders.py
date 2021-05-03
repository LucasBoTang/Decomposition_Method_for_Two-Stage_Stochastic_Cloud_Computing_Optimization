import time
from gurobipy import *
import numpy as np


def multiBenders(d, cutViolationTolerance=1e-4, epsilon=1e-4):
    """
    Multi-cut Benders decomposition
    """
    # build the master problem
    MP, xr, yr, n = buildMP(d)
    # build subproblems
    SP, xu, xo, yu, yo, f = buildSP(d)

    # init
    bestUB = GRB.INFINITY
    cutFound = True
    noIters = 0
    noCuts = 0
    tick = time.time()

    # benders loop
    print()
    while cutFound:
        noIters += 1
        cutFound = False
        print('Iteration {}:'.format(noIters))

        # Solve MP
        MP.update()
        MP.optimize()
        MPobj = MP.objVal
        print('MPobj：{:.2f}'.format(MPobj))

        # get first-stage varibles
        xrsol = {}
        for u in d.users:
            for v in d.VMs:
                for p in d.providers:
                    xrsol[u,v,p] = xr[u,v,p].x
        yrsol = {}
        for u in d.users:
            for r in d.routers:
                yrsol[u,r] = yr[u,r].x
        # get etas
        nsol = {}
        for s in d.scenarios:
            nsol[s] = n[s].x

        # current upper bound (first part)
        UB = sum(d.VM_rcost[v] * xrsol[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
           + sum(d.R_rcost[r] * yrsol[u,r] for r in d.routers for u in d.users)

        for s in d.scenarios:
            # solve subproblem and get dual solution
            qvalue, vu_pisol, ru_pisol, c_pisol, s_pisol, m_pisol, b_pisol, d_pisol = \
            modifyAndSolveSP(s, xrsol, yrsol, SP, xu, xo, yu, yo, d)
            # check dual solution
            dualSPobj = sum(xrsol[u,v,p] * vu_pisol[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
                      + sum(yrsol[u,r] * ru_pisol[u,r] for r in d.routers for u in d.users) \
                      + sum(c_pisol[p] * d.P_CCapacity[p] if d.P_CCapacity[p] != float('inf') else 0 for p in d.providers) \
                      + sum(s_pisol[p] * d.P_SCapacity[p] if d.P_SCapacity[p] != float('inf') else 0 for p in d.providers) \
                      + sum(m_pisol[p] * d.P_MCapacity[p] if d.P_MCapacity[p] != float('inf') else 0 for p in d.providers) \
                      + sum(b_pisol[r] * d.R_BCapacity[r] for r in d.routers) \
                      + sum(d_pisol[u,v] * d.VM_demands[s,u,v] for v in d.VMs for u in d.users)
            assert abs(dualSPobj - qvalue) < 1e-4, 'Strong duality'

            # current upper bound (second part)
            UB += d.prob[s] * qvalue

            # check whether a violated Benders cut is found
            cutFound_s = nsol[s] < qvalue - cutViolationTolerance
            expr = sum(xr[u,v,p] * vu_pisol[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
                 + sum(yr[u,r] * ru_pisol[u,r] for r in d.routers for u in d.users) \
                 + sum(c_pisol[p] * d.P_CCapacity[p] if d.P_CCapacity[p] != float('inf') else 0 for p in d.providers) \
                 + sum(s_pisol[p] * d.P_SCapacity[p] if d.P_SCapacity[p] != float('inf') else 0 for p in d.providers) \
                 + sum(m_pisol[p] * d.P_MCapacity[p] if d.P_MCapacity[p] != float('inf') else 0 for p in d.providers) \
                 + sum(b_pisol[r] * d.R_BCapacity[r] for r in d.routers) \
                 + sum(d_pisol[u,v] * d.VM_demands[s,u,v] for v in d.VMs for u in d.users)
            if cutFound_s:
                cutFound = True
                noCuts += 1
                MP.addConstr(n[s] >= expr)

        # update best upper bound
        bestUB = min(UB, bestUB)
        print('Current UB: {:.2f}'.format(UB))
        print('Best UB: {:.2f}'.format(bestUB))
        print()

        # convergence check
        if (bestUB - MPobj) / (1 + abs(bestUB)) <= epsilon:
            print('The algorithm converges.')
            break

    tock = time.time()
    print('Original problem is optimal.')
    print('Optimal obj: {:.4f}'.format(MPobj))
    print('VM:')
    for u in d.users:
        for v in d.VMs:
            for p in d.providers:
                print('  xr[{}, {}, {}] = {}'.format(u,v,p,int(xr[u,v,p].x)))
    print('Routers:')
    for u in d.users:
        for r in d.routers:
            print('  yr[{}, {}] = {:.2f}'.format(u,r,int(yr[u,r].x)))
    print('NoIters: {}'.format(noIters))
    print('NoCuts: {}'.format(noCuts))
    elapsed = tock - tick
    print('Elapse Time: {:.4f}'.format(elapsed))

    return MPobj, elapsed, noIters, noCuts


def buildMP(d):
    """
    Build the master problem
    """
    # create a new master
    MP = Model('MP')

    # turn off output
    MP.Params.outputFlag = 0
    # dual simplex
    MP.Params.method = 1

    # first-stage variables:
    # VMs reservation
    xr = MP.addVars(d.users, d.VMs, d.providers, vtype=GRB.INTEGER, name='xr')
    # routers reservation
    yr = MP.addVars(d.users, d.routers, vtype=GRB.CONTINUOUS, name='yr')

    # second stage expectation
    n = MP.addVars(d.scenarios, vtype=GRB.CONTINUOUS, name='eta')

    # objective function
    obj = quicksum(d.VM_rcost[v] * xr[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
        + quicksum(d.R_rcost[r] * yr[u,r] for r in d.routers for u in d.users) \
        + quicksum(d.prob[s] * n[s] for s in d.scenarios)
    MP.setObjective(obj)
    # model sense
    MP.modelSense = GRB.MINIMIZE

    return MP, xr, yr, n


def buildSP(d):
    """
    Build the subproblems
    """
    # create a new primal subproblem
    SP = Model('SP')

    # turn off output
    SP.Params.outputFlag = 0
    # dual simplex
    SP.Params.method = 1

    # second-stage varibles:
    # VMs utilization
    xu = SP.addVars(d.users, d.VMs, d.providers, vtype=GRB.CONTINUOUS, name='xu')
    # routers utilization
    yu = SP.addVars(d.users, d.routers, vtype=GRB.CONTINUOUS, name='yu')
    # VMs on-demand
    xo = SP.addVars(d.users, d.VMs, d.providers, vtype=GRB.CONTINUOUS, name='xo')
    # routers on-demand
    yo = SP.addVars(d.users, d.routers, vtype=GRB.CONTINUOUS, name='yo')
    # network flow
    f = SP.addVars(d.users, d.arcs, vtype=GRB.CONTINUOUS, name='f')

    # model sense
    SP.modelSense = GRB.MINIMIZE

    # constraints:
    # utilization bound (init rhs = 0)
    SP.addConstrs((xu[u,v,p] <= 0 for p in d.providers for v in d.VMs for u in d.users),
                  name='VM utilization bound')
    SP.addConstrs((yu[u,r] <= 0 for r in d.routers for u in d.users),
                  name='R utilization bound')
    # capacity
    SP.addConstrs((quicksum(d.VM_CDemand[v] * (xu[u,v,p] + xo[u,v,p]) for u in d.users for v in d.VMs) <= d.P_CCapacity[p]
                   for p in d.providers), name='CPU capacity')
    SP.addConstrs((quicksum(d.VM_SDemand[v] * (xu[u,v,p] + xo[u,v,p]) for u in d.users for v in d.VMs) <= d.P_SCapacity[p]
                   for p in d.providers), name='Storage capacity')
    SP.addConstrs((quicksum(d.VM_MDemand[v] * (xu[u,v,p] + xo[u,v,p]) for u in d.users for v in d.VMs) <= d.P_MCapacity[p]
                   for p in d.providers), name='Memory capacity')
    SP.addConstrs((quicksum(yu[u,r] + yo[u,r] for u in d.users) <= d.R_BCapacity[r]
                   for r in d.routers), name='Bandwidth capacity')
    # VM demand (init rhs = 0)
    SP.addConstrs((quicksum(xu[u,v,p] + xo[u,v,p] for p in d.providers) >= 0
                   for v in d.VMs for u in d.users), name='VM demand')
    # network flow
    SP.addConstrs((quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_in == r) == \
                   quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_out == r)
                   for u in d.users for r in d.routers), name='R balance')
    SP.addConstrs((quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_out == r) == yu[u,r] + yo[u,r]
                   for u in d.users for r in d.routers), name='R usage')
    SP.addConstrs((quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_out == p) >= \
                   quicksum(d.VM_BDemand[v] * (xu[u,v,p] + xo[u,v,p]) for v in d.VMs)
                   for p in d.providers for u in d.users), name='R demand')
    SP.addConstrs((quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_in == u) == \
                   quicksum(f[u,e_out,e_in] for e_out, e_in in d.arcs if e_out[0] == 'P')
                   for u in d.users), name='U balance')

    SP.update()
    return SP, xu, xo, yu, yo, f


def modifyAndSolveSP(s, xrsol, yrsol, SP, xu, xo, yu, yo, d):
    """
    modify constraints rhs with scenario and fixed first-stage varibles
    solve and return dual solution
    """
    # modify rhs
    for constr in SP.getConstrs():
        name, index = constr.constrName[:-1].split('[')
        index = index.split(',')
        if name == 'VM utilization bound':
            p, v, u = index
            constr.rhs = xrsol[u,v,p]
        elif name == 'R utilization bound':
            r, u = index
            constr.rhs = yrsol[u,r]
        elif name == 'VM demand':
            v, u = index
            constr.rhs = d.VM_demands[s,u,v]

    # modify obj
    obj = quicksum(d.VM_ucost[s,v] * xu[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
        + quicksum(d.R_ucost[s,r] * yu[u,r] for r in d.routers for u in d.users) \
        + quicksum(d.VM_ocost[s,v] * xo[u,v,p] for p in d.providers for v in d.VMs for u in d.users) \
        + quicksum(d.R_ocost[s,r] * yo[u,r] for r in d.routers for u in d.users)
    SP.setObjective(obj)

    # solve
    SP.optimize()
    SPobj = SP.objVal
    # print('Subproblem {}'.format(s))
    # print('SPobj: {:.2f}'.format(SPobj))

    # dual solution
    vu_pisol = {} # VM utilization
    ru_pisol = {} # router utilization
    c_pisol = {} # CPU capacity
    s_pisol = {} # storage capacity
    m_pisol = {} # memory capacity
    b_pisol = {} # bandwith capacity
    d_pisol = {} # VM demand
    for constr in SP.getConstrs():
        name, index = constr.constrName[:-1].split('[')
        if name == 'VM utilization bound':
            p, v, u = index.split(',')
            vu_pisol[u,v,p] = constr.pi
        elif name == 'R utilization bound':
            r, u = index.split(',')
            ru_pisol[u,r] = constr.pi
        elif name == 'CPU capacity':
            c_pisol[index] = constr.pi
        elif name == 'Storage capacity':
            s_pisol[index] = constr.pi
        elif name == 'Memory capacity':
            m_pisol[index] = constr.pi
        elif name == 'Bandwidth capacity':
            b_pisol[index] = constr.pi
        elif name == 'VM demand':
            v, u = index.split(',')
            d_pisol[u,v] = constr.pi

    return SPobj, vu_pisol, ru_pisol, c_pisol, s_pisol, m_pisol, b_pisol, d_pisol
