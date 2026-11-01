import argparse,json
from .dataset import validate_dataset
from .acceptance import refresh_reviews

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 d=sub.add_parser('validate-dataset');d.add_argument('manifest');d.add_argument('--smoke',action='store_true')
 r=sub.add_parser('refresh-reviews');r.add_argument('output_dir')
 x=sub.add_parser('run-suite');x.add_argument('config');x.add_argument('--resume',action='store_true')
 args=p.parse_args()
 if args.command=='run-suite':
  from .runner import run_config
  print(json.dumps(run_config(args.config,resume=args.resume),indent=2));return
 if args.command=='validate-dataset':
  report=validate_dataset(args.manifest,acceptance=not args.smoke)
  print(json.dumps({k:v for k,v in report.items() if k not in ('clips','requests','data')},indent=2))
  raise SystemExit(0 if report['valid'] else 2)
 print(json.dumps(refresh_reviews(args.output_dir),indent=2))
if __name__=='__main__':main()
