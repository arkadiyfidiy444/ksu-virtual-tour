import struct, json, numpy as np
class GLB:
    def __init__(self, path):
        b = open(path,'rb').read(); off = 12
        while off < len(b):
            cl, ct = struct.unpack('<I4s', b[off:off+8])
            if ct == b'JSON': self.g = json.loads(b[off+8:off+8+cl])
            elif ct.startswith(b'BIN'): self.bin = memoryview(b)[off+8:off+8+cl]
            off += 8+cl
        self.cache = {}
    def acc(self, i):
        if i in self.cache: return self.cache[i]
        a = self.g['accessors'][i]; bv = self.g['bufferViews'][a['bufferView']]
        n = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]; dt = {5126:np.float32,5123:np.uint16,5125:np.uint32,5121:np.uint8}[a['componentType']]
        off = bv.get('byteOffset',0)+a.get('byteOffset',0); stride = bv.get('byteStride')
        if stride and stride != n*np.dtype(dt).itemsize:
            raw = np.frombuffer(self.bin, dtype=np.uint8, count=stride*a['count'], offset=off).reshape(a['count'], stride)[:, :n*np.dtype(dt).itemsize]
            arr = raw.copy().view(dt).reshape(a['count'], n)
        else: arr = np.frombuffer(self.bin, dtype=dt, count=a['count']*n, offset=off).reshape(a['count'], n)
        self.cache[i] = arr; return arr
    @staticmethod
    def node_matrix(n):
        if 'matrix' in n: return np.array(n['matrix'], dtype=np.float64).reshape(4,4).T
        t = np.array(n.get('translation',[0,0,0]), dtype=np.float64); q = n.get('rotation',[0,0,0,1]); s = np.array(n.get('scale',[1,1,1]), dtype=np.float64)
        x,y,z,w = q; R = np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
        M = np.eye(4); M[:3,:3] = R*s; M[:3,3] = t; return M
    def prims(self, node):
        """yield (material_name, world_positions(Nx3), triangles(Mx3 indices))"""
        M = self.node_matrix(node); m = self.g['meshes'][node['mesh']]
        for p in m['primitives']:
            pos = self.acc(p['attributes']['POSITION']).astype(np.float64); w = pos @ M[:3,:3].T + M[:3,3]
            idx = self.acc(p['indices']).reshape(-1,3).astype(np.int64) if 'indices' in p else np.arange(len(pos)).reshape(-1,3)
            yield self.g['materials'][p['material']].get('name','') if 'material' in p else '', w, idx
