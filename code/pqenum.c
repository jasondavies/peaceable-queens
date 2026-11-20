// pqenum.c -- (derived from pq2.c) ENUMERATES all labellings with min(W,B) >= T, without symmetry
// reduction, printing the W/B cell board of each (lines with no live candidate cell get only label B).
// Used for A260680 (number of inequivalent optimal configurations).
// pq2.c -- peaceable queens (OEIS A250000): two-stage exact search.
//
// Stage 1: enumerate labellings of rows and columns (R = W-rows, C = W-columns) by DFS in D4-invariant
//          groups {row e, row n-1-e, col e, col n-1-e}, e = 0,1,..., pruning prefixes that are not
//          lex-minimal under G = D4 x {colour swap} (NOTES Lemma 4) and by the count bound.
// Stage 2: for fixed (R,C), W-candidates are R x C, B-candidates are R' x C'; a candidate cell is W (B) iff
//          its diagonal and antidiagonal are both W (B).  DFS over diagonal/antidiagonal labels, with the
//          Lagrangian bound  max min(W,B) <= min_p max_x [p W + (Q-p) B]/Q  where the inner max is a
//          pairwise supermodular maximisation = min cut on the 4n-2 diagonal nodes (NOTES Lemmas 2,3).
//
// Work units ("cubes"): canonical stage-1 prefixes of K groups (4K lines; 2 or 3 lines for the middle
// group when n is odd).  Each cube is solved independently and logged.
//
// usage: pq2 n T [-K groups] [-list] [-cube lo:hi] [-m M -j J] [-Q q] [-v]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include <errno.h>

#define MAXN 24
#define MAXL (6*MAXN)
static int n,T,NL,NC,ND;     // ND = 2n-1 diagonals (and as many antidiagonals)
static int Q=256;
static int lab[MAXL];        // -1 free, 1 W, 0 B ; lines: rows 0..n-1, cols n..2n-1, diag 2n+(i-j+n-1), anti 4n-1+(i+j)
static int orderRC[2*MAXN], grpEnd[MAXN+1], NG; // stage-1 order and group boundaries
static int lineSym[16][MAXL], symFlip[16], invPos[16][2*MAXN];
static long long nodes1=0, leaves=0, nodes2=0, flows=0;
static int found=0; static int solLab[MAXL];
static int verbose=0, useSym=0;

static int rowL(int i){return i;} static int colL(int j){return n+j;}
static int diaL(int i,int j){return 2*n+(i-j+n-1);} static int antL(int i,int j){return 4*n-1+(i+j);}
static int lineType(int l){ return l<n?0:(l<2*n?1:(l<4*n-1?2:3)); }
static void d4map(int g,int i,int j,int*oi,int*oj){
  int a=i,b=j,m=n-1;
  switch(g&7){case 0:*oi=a;*oj=b;break; case 1:*oi=b;*oj=m-a;break; case 2:*oi=m-a;*oj=m-b;break;
    case 3:*oi=m-b;*oj=a;break; case 4:*oi=a;*oj=m-b;break; case 5:*oi=m-a;*oj=b;break;
    case 6:*oi=b;*oj=a;break; default:*oi=m-b;*oj=m-a;break;}
}
// cell lists of lines (for checking only)
static int lineCells[MAXL][MAXN], lineLen[MAXL], cellLine[MAXN*MAXN][4];
static void buildGeometry(void){
  NL=6*n-2; NC=n*n; ND=2*n-1;
  for(int l=0;l<NL;l++) lineLen[l]=0;
  for(int i=0;i<n;i++)for(int j=0;j<n;j++){int c=i*n+j; int ls[4]={rowL(i),colL(j),diaL(i,j),antL(i,j)};
    for(int k=0;k<4;k++){cellLine[c][k]=ls[k]; lineCells[ls[k]][lineLen[ls[k]]++]=c;}}
  for(int g=0;g<16;g++){symFlip[g]=g>>3; int gg=g&7;
    int swapRC=(gg==1||gg==3||gg==6||gg==7), swapDA=(gg==1||gg==3||gg==4||gg==5);
    for(int l=0;l<NL;l++){int c=lineCells[l][0],oi,oj; d4map(g,c/n,c%n,&oi,&oj);
      int t=lineType(l), nt=t<2?(t^swapRC):(2+((t-2)^swapDA));
      lineSym[g][l]= nt==0?rowL(oi):nt==1?colL(oj):nt==2?diaL(oi,oj):antL(oi,oj);}}
  // verify group action: bijection, and maps the 4 lines of each cell to the 4 lines of the image cell
  for(int g=0;g<16;g++){int seen[MAXL]={0};
    for(int l=0;l<NL;l++) if(seen[lineSym[g][l]]++){fprintf(stderr,"sym not bijective\n");exit(1);}
    for(int c=0;c<NC;c++){int oi,oj; d4map(g,c/n,c%n,&oi,&oj); int oc=oi*n+oj;
      for(int k=0;k<4;k++){int im=lineSym[g][cellLine[c][k]],in=0; for(int t=0;t<4;t++) if(cellLine[oc][t]==im) in=1;
        if(!in){fprintf(stderr,"sym cell mismatch\n");exit(1);}}}}
  // stage-1 order: edge-in groups
  int k=0; NG=0; grpEnd[0]=0;
  for(int e=0;e<(n+1)/2;e++){int a=e,b=n-1-e;
    orderRC[k++]=rowL(a); if(b!=a) orderRC[k++]=rowL(b); orderRC[k++]=colL(a); if(b!=a) orderRC[k++]=colL(b);
    grpEnd[++NG]=k;}
  // check group invariance, build preimage positions: invPos[g][i] = position of the line m with g(m)=orderRC[i]
  int pos[MAXL]; for(int l=0;l<NL;l++)pos[l]=-1; for(int i=0;i<2*n;i++)pos[orderRC[i]]=i;
  for(int g=0;g<16;g++) for(int i=0;i<2*n;i++){ int img=lineSym[g][orderRC[i]]; int pi=pos[img];
      // group containing i must map into the same group
      int gi=0; while(grpEnd[gi+1]<=i) gi++; if(pi<grpEnd[gi]||pi>=grpEnd[gi+1]){fprintf(stderr,"group not invariant\n");exit(1);}
      invPos[g][pi]=i; }
}
// prefix positions [0,D) canonical?  image sequence s_g(i) = lab[orderRC[invPos[g][i]]] ^ flip
static int isCanonical(int D){
  for(int g=1;g<16;g++){
    for(int i=0;i<D;i++){ int v=lab[orderRC[i]], v2=lab[orderRC[invPos[g][i]]]^symFlip[g];
      if(v2<v) return 0; if(v2>v) break; }
  }
  return 1;
}

// ---------------- stage 2 data ----------------
// diag index d in [0,ND): line 2n+d;  anti index a in [0,ND): line 4n-1+a.
// candidate cells: kind[d][a] = +1 W-cand, -1 B-cand, 0 none (also 0 if (d,a) not a cell).
static int kind[2*MAXN][2*MAXN];
static int cellDA[MAXN*MAXN][2];
static int xd[2*MAXN], ya[2*MAXN]; // diag/anti labels: -1 free, 1 W, 0 B
static int nWc,nBc;                // # candidates
static int possW, possB;           // # candidates not yet killed
// ---------------- max flow ----------------
#define MAXV (4*MAXN+4)
#define MAXE (2*(MAXN*MAXN*2+8*MAXN+8))
static int head[MAXV],nxt[MAXE],to[MAXE],cp[MAXE],ne_,nv_,lvl[MAXV],it_[MAXV],qq[MAXV];
static inline void addE(int u,int v,int c){ if(c<=0) return;
  to[ne_]=v;cp[ne_]=c;nxt[ne_]=head[u];head[u]=ne_++; to[ne_]=u;cp[ne_]=0;nxt[ne_]=head[v];head[v]=ne_++; }
static int bfs(int s,int t){ for(int i=0;i<nv_;i++)lvl[i]=-1; int qh=0,qt=0; qq[qt++]=s; lvl[s]=0;
  while(qh<qt){int u=qq[qh++]; for(int e=head[u];e>=0;e=nxt[e]) if(cp[e]>0&&lvl[to[e]]<0){lvl[to[e]]=lvl[u]+1;qq[qt++]=to[e];}}
  return lvl[t]>=0; }
static int dfsF(int u,int t,int f){ if(u==t) return f;
  for(int*e=&it_[u];*e>=0;*e=nxt[*e]){int v=to[*e];
    if(cp[*e]>0&&lvl[v]==lvl[u]+1){int d=dfsF(v,t,f<cp[*e]?f:cp[*e]); if(d>0){cp[*e]-=d;cp[*e^1]+=d;return d;}}}
  return 0; }
static long long maxflow(int s,int t){ long long fl=0; flows++;
  while(bfs(s,t)){ for(int i=0;i<nv_;i++)it_[i]=head[i]; int f; while((f=dfsF(s,t,1<<30))>0) fl+=f; } return fl; }

// U_p = max over completions of p*W + (Q-p)*B (exact).  Completion from source side -> cx,cy; counts W,B.
static int cx[2*MAXN],cy[2*MAXN];
static long long evalU(int p,int*Wo,int*Bo){
  int A=p,Bw=Q-p; long long gains=0;
  int s=0,t=1; nv_=2+2*ND; ne_=0; for(int i=0;i<nv_;i++)head[i]=-1;
  static int capS[2*2*MAXN],capT[2*2*MAXN];
  for(int i=0;i<2*ND;i++){capS[i]=capT[i]=0;}
  for(int c=0;c<NC;c++){int d=cellDA[c][0],a=cellDA[c][1],k=kind[d][a]; if(!k) continue;
    int vd=xd[d],va=ya[a];
    if(k>0){ if(vd==0||va==0||A==0) continue; gains+=A;
      if(vd<0&&va<0){ capS[d]+=A; addE(2+d,2+ND+a,A); }
      else if(vd<0) capS[d]+=A; else if(va<0) capS[ND+a]+=A; }
    else { if(vd==1||va==1||Bw==0) continue; gains+=Bw;
      if(vd<0&&va<0){ capT[d]+=Bw; addE(2+ND+a,2+d,Bw); }
      else if(vd<0) capT[d]+=Bw; else if(va<0) capT[ND+a]+=Bw; }
  }
  for(int i=0;i<2*ND;i++){ int m=capS[i]<capT[i]?capS[i]:capT[i]; // cancel common part (always cut)
    gains-=m; addE(s,2+i,capS[i]-m); addE(2+i,t,capT[i]-m); }
  long long cut=maxflow(s,t);
  for(int d=0;d<ND;d++) cx[d]= xd[d]>=0?xd[d]:(lvl[2+d]>=0);
  for(int a=0;a<ND;a++) cy[a]= ya[a]>=0?ya[a]:(lvl[2+ND+a]>=0);
  int W=0,B=0;
  for(int c=0;c<NC;c++){int d=cellDA[c][0],a=cellDA[c][1],k=kind[d][a];
    if(k>0&&cx[d]&&cy[a])W++; else if(k<0&&!cx[d]&&!cy[a])B++;}
  *Wo=W;*Bo=B; return gains-cut;
}
static void recordSolution(void){
  found=1; for(int l=0;l<NL;l++) solLab[l]=lab[l];
  for(int d=0;d<ND;d++) solLab[2*n+d]=cx[d]; for(int a=0;a<ND;a++) solLab[4*n-1+a]=cy[a];
}
static int boundPrune(int*pHint){
  int lo=0,hi=Q,p=*pHint;
  for(int it=0;it<20;it++){
    int W,B; long long U=evalU(p,&W,&B);
    if(W>=T&&B>=T){ return 0; }
    if(U<(long long)Q*T){ *pHint=p; return 1; }
    if(W>B) hi=p-1; else if(W<B) lo=p+1; else return 0;
    if(lo>hi) return 0;
    p=lo+(hi-lo)/2;
  }
  return 0;
}
// stage-2 DFS order: diagonals and antidiagonals interleaved, longest first
static int ord2[4*MAXN], N2;
static void setDA(int k,int v){ // k<ND diag, else anti
  if(k<ND){ int d=k; xd[d]=v; for(int a=0;a<ND;a++){int t=kind[d][a]; if(t>0&&v==0&&ya[a]!=0) possW--; if(t<0&&v==1&&ya[a]!=1) possB--;} }
  else { int a=k-ND; ya[a]=v; for(int d=0;d<ND;d++){int t=kind[d][a]; if(t>0&&v==0&&xd[d]!=0) possW--; if(t<0&&v==1&&xd[d]!=1) possB--;} }
}
static void unsetDA(int k){
  if(k<ND){ int d=k,v=xd[d]; xd[d]=-1; for(int a=0;a<ND;a++){int t=kind[d][a]; if(t>0&&v==0&&ya[a]!=0) possW++; if(t<0&&v==1&&ya[a]!=1) possB++;} }
  else { int a=k-ND,v=ya[a]; ya[a]=-1; for(int d=0;d<ND;d++){int t=kind[d][a]; if(t>0&&v==0&&xd[d]!=0) possW++; if(t<0&&v==1&&xd[d]!=1) possB++;} }
}
static long long emitted=0;
static void emitBoard(void){
  int W=0,B=0; char buf[MAXN*MAXN+1];
  for(int c=0;c<NC;c++){int d=cellDA[c][0],a=cellDA[c][1],k=kind[d][a]; char ch='.';
    if(k>0&&xd[d]==1&&ya[a]==1){ch='W';W++;} else if(k<0&&xd[d]==0&&ya[a]==0){ch='B';B++;} buf[c]=ch;}
  buf[NC]=0; if(W>=T&&B>=T){ printf("S %d %d %s\n",W,B,buf); emitted++; }
}
static void dfs2(int dep,int pHint){
  nodes2++;
  if(possW<T||possB<T) return;
  if(boundPrune(&pHint)) return;
  if(dep==N2){ emitBoard(); return; }
  int k=ord2[dep];
  // is any candidate cell on this line still alive (other line not of the opposite colour)?
  int live=0;
  if(k<ND){ for(int a=0;a<ND;a++){int t=kind[k][a]; if((t>0&&ya[a]!=0)||(t<0&&ya[a]!=1)) live=1;} }
  else { int a=k-ND; for(int d=0;d<ND;d++){int t=kind[d][a]; if((t>0&&xd[d]!=0)||(t<0&&xd[d]!=1)) live=1;} }
  for(int v=0;v<=(live?1:0);v++){ setDA(k,v); dfs2(dep+1,pHint); unsetDA(k); }
}
static long long leafPrunedRoot=0, leafSearched=0;
static int rootP=-1;
static void stage2(void){
  leaves++;
  nWc=nBc=0;
  for(int c=0;c<NC;c++){int i=c/n,j=c%n,d=cellDA[c][0],a=cellDA[c][1];
    int k = (lab[rowL(i)]==1&&lab[colL(j)]==1) ? 1 : (lab[rowL(i)]==0&&lab[colL(j)]==0) ? -1 : 0;
    kind[d][a]=k; if(k>0)nWc++; else if(k<0)nBc++; }
  if(nWc<T||nBc<T) return;
  possW=nWc; possB=nBc;
  for(int d=0;d<ND;d++){xd[d]=-1;ya[d]=-1;}
  int p = rootP>=0?rootP:Q/2;
  long long before=nodes2;
  dfs2(0,p);
  if(nodes2-before>1) leafSearched++; else leafPrunedRoot++;
}
// ---------------- stage 1 ----------------
static int rcount[2],ccount[2]; // # rows labelled W / B so far (index by label), same for cols
static int D1;  // depth at which cubes are formed
static long long cubeId=0, cubeLo=0, cubeHi=-1; static int listMode=0, modM=1, modJ=0;
static void dfs1(int d){
  nodes1++;
  // count bound: W-cells <= (#rows not B)(#cols not B), B-cells <= (#rows not W)(#cols not W)
  if((n-rcount[0])*(n-ccount[0])<T || (n-rcount[1])*(n-ccount[1])<T) return;
  if(d==2*n){ stage2(); return; }
  int l=orderRC[d];
  for(int v=0;v<=1&&!found;v++){
    lab[l]=v; if(l<n) rcount[v]++; else ccount[v]++;
    int ge=0; for(int g=1;g<=NG;g++) if(grpEnd[g]==d+1) ge=1;
    if(!ge || !useSym || isCanonical(d+1)){
      if(d+1==D1 && D1<2*n+1){
        long long id=cubeId++;
        if(listMode){ printf("cube %lld ",id); for(int i=0;i<D1;i++) putchar('0'+lab[orderRC[i]]); printf("\n"); }
        else if(id>=cubeLo && (cubeHi<0||id<cubeHi) && id%modM==modJ){
          long long a1=nodes1,a2=nodes2,a3=leaves,a4=flows,a5=leafSearched; clock_t t0=clock();
          dfs1(d+1);
          printf("cube %lld ",id); for(int i=0;i<D1;i++) putchar('0'+lab[orderRC[i]]);
          printf(" n1 %lld leaves %lld searched %lld n2 %lld flows %lld time %.3f %s\n",nodes1-a1,leaves-a3,leafSearched-a5,nodes2-a2,flows-a4,
                 (double)(clock()-t0)/CLOCKS_PER_SEC, found?"FOUND":"UNSAT");
          fflush(stdout);
        }
      } else dfs1(d+1);
    }
    if(l<n) rcount[v]--; else ccount[v]--; lab[l]=-1;
  }
}

static int verifySolution(int*Wo,int*Bo){ // independent recount from the full labelling
  int W=0,B=0;
  for(int c=0;c<NC;c++){int sw=1,sb=1; for(int k=0;k<4;k++){int v=solLab[cellLine[c][k]]; if(v!=1)sw=0; if(v!=0)sb=0;} W+=sw;B+=sb;}
  *Wo=W;*Bo=B; return W>=T&&B>=T;
}

// ---------------- self test: evalU vs brute force over all completions ----------------
static int selftest=0;
static uint64_t rng=88172645463325252ULL; static uint64_t xr(void){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;return rng;}
static int runSelftest(int iters){
  int bad=0;
  for(int it=0;it<iters;it++){
    for(int i=0;i<n;i++){lab[rowL(i)]=xr()&1; lab[colL(i)]=xr()&1;}
    for(int c=0;c<NC;c++){int i=c/n,j=c%n,d=cellDA[c][0],a=cellDA[c][1];
      kind[d][a]=(lab[rowL(i)]==1&&lab[colL(j)]==1)?1:(lab[rowL(i)]==0&&lab[colL(j)]==0)?-1:0;}
    int fr[4*MAXN],nf=0;
    for(int d=0;d<ND;d++){ int r=xr()%3; xd[d]= r==2?-1:r; if(xd[d]<0) fr[nf++]=d; }
    for(int a=0;a<ND;a++){ int r=xr()%3; ya[a]= r==2?-1:r; if(ya[a]<0) fr[nf++]=ND+a; }
    if(nf>22) continue;
    int p=xr()%(Q+1); int W,B; long long U=evalU(p,&W,&B);
    // brute force
    long long best=-1; int sx[2*MAXN],sy[2*MAXN]; memcpy(sx,xd,sizeof sx); memcpy(sy,ya,sizeof sy);
    for(long long m=0;m<(1LL<<nf);m++){
      for(int k=0;k<nf;k++){int v=(m>>k)&1; if(fr[k]<ND) xd[fr[k]]=v; else ya[fr[k]-ND]=v;}
      long long w=0,b=0;
      for(int c=0;c<NC;c++){int d=cellDA[c][0],a=cellDA[c][1],k=kind[d][a]; if(k>0&&xd[d]==1&&ya[a]==1)w++; if(k<0&&xd[d]==0&&ya[a]==0)b++;}
      long long v=p*w+(Q-p)*b; if(v>best)best=v;
    }
    memcpy(xd,sx,sizeof sx); memcpy(ya,sy,sizeof sy);
    // the completion returned must achieve U
    if(best!=U || (long long)p*W+(long long)(Q-p)*B!=U){ bad++; printf("MISMATCH it=%d p=%d U=%lld brute=%lld W=%d B=%d\n",it,p,U,best,W,B); }
  }
  printf("selftest n=%d iters=%d mismatches=%d\n",n,iters,bad); return bad?4:0;
}
// strict integer argument parsing: the whole string must be a decimal integer in [lo,hi]
static long long argInt(const char*s,long long lo,long long hi,const char*what){
  char*e; errno=0; long long v=strtoll(s,&e,10);
  if(errno||e==s||*e||v<lo||v>hi){fprintf(stderr,"invalid %s '%s' (allowed %lld..%lld)\n",what,s,lo,hi); exit(1);}
  return v;
}
static const char*nextArg(int*i,int argc,char**argv){ if(*i+1>=argc){fprintf(stderr,"missing value after %s\n",argv[*i]); exit(1);} return argv[++*i]; }
int main(int argc,char**argv){
  if(argc<3){fprintf(stderr,"usage: n T [options]\n");return 1;}
  n=(int)argInt(argv[1],1,MAXN,"n"); T=(int)argInt(argv[2],0,MAXN*MAXN,"T"); int K=-1, cubeGiven=0;
  for(int i=3;i<argc;i++){
    if(!strcmp(argv[i],"-K")) K=(int)argInt(nextArg(&i,argc,argv),1,MAXN,"K");   // K=0 would emit no cubes
    else if(!strcmp(argv[i],"-list")) listMode=1;
    else if(!strcmp(argv[i],"-cube")){ const char*v=nextArg(&i,argc,argv); char a[32],b[32];
      int used=-1; if(strlen(v)>60||sscanf(v,"%31[0-9]:%31[0-9]%n",a,b,&used)!=2||used<0||v[used]){fprintf(stderr,"invalid -cube '%s' (want lo:hi)\n",v); exit(1);}
      cubeLo=argInt(a,0,(1LL<<40),"cube lo"); cubeHi=argInt(b,1,(1LL<<40),"cube hi");
      if(cubeLo>=cubeHi){fprintf(stderr,"invalid -cube: lo must be < hi\n"); exit(1);} cubeGiven=1; }
    else if(!strcmp(argv[i],"-m")) modM=(int)argInt(nextArg(&i,argc,argv),1,1<<20,"-m");
    else if(!strcmp(argv[i],"-j")) modJ=(int)argInt(nextArg(&i,argc,argv),0,1<<20,"-j");
    else if(!strcmp(argv[i],"-Q")) Q=(int)argInt(nextArg(&i,argc,argv),1,65536,"-Q");   // keeps every capacity sum < 2^31
    else if(!strcmp(argv[i],"-v")) verbose=1;
    else if(!strcmp(argv[i],"-nosym")) useSym=0;
    else if(!strcmp(argv[i],"-selftest")) selftest=(int)argInt(nextArg(&i,argc,argv),1,100000000,"-selftest");
    else {fprintf(stderr,"bad option '%s'\n",argv[i]);return 1;}
  }
  if(modJ>=modM){fprintf(stderr,"invalid partition: need 0 <= -j < -m\n"); return 1;}
  buildGeometry();
  if(K>NG){fprintf(stderr,"invalid -K %d: only %d groups for n=%d\n",K,NG,n); return 1;}
  if(cubeGiven&&K<0){fprintf(stderr,"-cube needs -K\n"); return 1;}
  for(int c=0;c<NC;c++){cellDA[c][0]=(c/n)-(c%n)+n-1; cellDA[c][1]=(c/n)+(c%n);}
  for(int d=0;d<ND;d++)for(int a=0;a<ND;a++)kind[d][a]=0;
  // stage-2 order: by length, diag then anti
  N2=0; for(int len=n;len>=1;len--){ for(int d=0;d<ND;d++) if(lineLen[2*n+d]==len) ord2[N2++]=d; for(int a=0;a<ND;a++) if(lineLen[4*n-1+a]==len) ord2[N2++]=ND+a; }
  for(int l=0;l<NL;l++)lab[l]=-1;
  if(selftest) return runSelftest(selftest);
  D1 = K<0 ? 2*n+1 : grpEnd[K];
  clock_t t0=clock();
  dfs1(0);
  double el=(double)(clock()-t0)/CLOCKS_PER_SEC;
  if(listMode){ printf("cubes %lld\n",cubeId); return 0; }
  if(cubeGiven&&!found&&cubeHi>cubeId){fprintf(stderr,"invalid -cube %lld:%lld: there are only %lld cubes\n",cubeLo,cubeHi,cubeId); return 1;}
  printf("emitted %lld\n",emitted);
  printf("n=%d T=%d K=%d %s nodes1=%lld leaves=%lld leafSearched=%lld nodes2=%lld flows=%lld cubes=%lld time=%.2fs\n",
         n,T,K,found?"FEASIBLE":"INFEASIBLE",nodes1,leaves,leafSearched,nodes2,flows,cubeId,el);
  if(found){ int W,B; int ok=verifySolution(&W,&B); printf("solution check: W=%d B=%d %s\nlabelling ",W,B,ok?"OK":"BAD");
    for(int l=0;l<NL;l++) printf("%d",solLab[l]); printf("\n");
    for(int i=0;i<n;i++){ printf("  "); for(int j=0;j<n;j++){int c=i*n+j,sw=1,sb=1; for(int k=0;k<4;k++){int v=solLab[cellLine[c][k]]; if(v!=1)sw=0; if(v!=0)sb=0;} putchar(sw?'W':sb?'B':'.');} printf("\n"); }
    if(!ok) return 3; }
  return 0;
}
