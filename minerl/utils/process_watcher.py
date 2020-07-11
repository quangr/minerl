import coloredlogs
import argparse
import psutil
import time
import shutil
import logging
import psutil
import subprocess
import os
import signal
from daemoniker import daemonize



logger = logging.getLogger('process_watcher')
MINERL_WATCHERS_DIR=os.path.join('logs', 'minerl_watchers')

CHILD_DIR_ARG = 'child-dirs'

def parse_args():
    """Parses the arguments for the process watcher.
    """
    parser = argparse.ArgumentParser(
        description='A general process watcher utility that ensures '
                    'that a parent and child process terminate uniformly.')
    parser.add_argument('parent_pid', type=int,
                        help='The PID of the parent process.')
    parser.add_argument('child_pid', type=int,
                        help='The PID of the child process.')
    parser.add_argument(f'--{CHILD_DIR_ARG}',
                        type=str, help='Temporary directories which should be deleted '
                                       'were the processes to terminate.',
                        nargs='+')
    return parser.parse_args()




def launch(parent_pid, child_pid, *temp_dirs):
    """Launches the process watcher with a PID.

    Args:
        parent_pid (int): The parent PID.
        child_pid (int): The child PID.

    Returns:
        psutil.Process: The process object of the watcher.
    """
    logger.info("Launhing process watcher daemonizer.")
    subprocess.check_call([
        'python', '-m', 'minerl.utils.process_watcher',
        str(parent_pid), str(child_pid),
        f'--{CHILD_DIR_ARG}'] + list(temp_dirs))
    logger.info("Process watcher daemonizer launched successfully.")



def reap_process_and_children(process, timeout=5):
    "Tries hard to terminate and ultimately kill all the children of this process."
    def on_process_wait_successful(proc):
        returncode = proc.returncode if hasattr(proc, 'returncode') else None
        logger.info("Process {} terminated with exit code {}".format(
            proc, returncode))
    
    def get_process_info(proc):
        return f"{proc.pid}:{proc.name()}:{proc.exe()} i {proc.status()}, owner {proc.ppid()}"

    procs = process.children(recursive=True)[::-1] + [process]
    logger.info(f"About to reap process tree of {get_process_info(process)}, "
                "printing process tree status in termination order:")
    for p in procs:
        logger.info(f"\t-{get_process_info(p)}")

    for p in procs:
        try:
            logger.info(f"Trying to SIGTERM {p.pid}:{p.name()}:{p.exe()} initial status {p.status()}, owner {p.ppid()}")
            p.terminate()
            try:
                p.wait(timeout=timeout)
                on_process_wait_successful(p)
            except psutil.TimeoutExpired:

                logger.info(
                    "Process {} survived SIGTERM; trying SIGKILL  (current status) {}, (owner) {}".format(p.pid, p.status(), p.ppid()))
                p.kill()

                try:
                    p.wait(timeout=timeout)
                    on_process_wait_successful(p)
                except psutil.TimeoutExpired:
                    # Give up
                    logger.info(
                    "Process {} survived SIGKILL; giving up (final status) {}, (owner) {}".format(p.pid, p.status(), p.ppid()))
        except psutil.NoSuchProcess:
            logger.info(f"Process {p} does not exist. (It may have already been reaped successfully)")


def main(args):
    """The primary process watcher program. 

    Args:
        args (--): Arguments from the process watcher.
    """


    # Wait for processes to be launched
    logger.info(
        f"Process watcher started between parent {args.parent_pid}"
        f" and child {args.child_pid} ")
    time.sleep(1)
    try:
        child = psutil.Process(args.child_pid)
    except psutil.NoSuchProcess:
        child = None
    try:
        parent = psutil.Process(args.parent_pid)
    except psutil.NoSuchProcess:
        parent = None

    while True:
        try:
            # Sleep for a short time, and check if subprocesses needed to be killed.
            time.sleep(0.1)

            if not parent.is_running() or parent is None:
                logger.info(
                    "Parent is not running, hence we need terminate the child.")
                if child is not None:
                    reap_process_and_children(child)
                    try:
                        for temp_dir in args[CHILD_DIR_ARG]:
                            shutil.rmtree(temp_dir)
                    except OSError:
                        logger.warning(
                            "Failed to delete temporary child directory. It may have already been removed.")
                    except KeyError:
                        # No CHILD_DIR_ARG provided.
                        pass
                return
            # Kill the watcher if the child is no longer running.
            # If you want to attempt to restart the child on failure, this
            # would be the location to do so.
            if not child.is_running():
                logger.info(
                    "Child is not running anymore, launcher can terminate."
                )
                return
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    args = parse_args()
    os.makedirs(MINERL_WATCHERS_DIR, exist_ok=True)

    os_cur_dir = os.path.abspath(os.getcwd())
    watcher_name = f'watcher_{args.parent_pid}-{args.child_pid}'


    daemonize(os.path.join(os_cur_dir,MINERL_WATCHERS_DIR, watcher_name + '.pid'))   

    coloredlogs.install(level=logging.DEBUG, stream=open(
        os.path.join(os_cur_dir, MINERL_WATCHERS_DIR, watcher_name + '.log'), 'w'
    ))

    main(args)
    exit() # Correctly invoke the at_exit handlers and any other os clean up _explicitly_!

        
