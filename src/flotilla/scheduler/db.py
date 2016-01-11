import logging
import time
from boto.dynamodb2.exceptions import ItemNotFound
from boto.dynamodb2.items import Item
from collections import defaultdict

logger = logging.getLogger('flotilla')

INSTANCE_EXPIRY = 300
REV_LENGTH = 64


class FlotillaSchedulerDynamo(object):
    def __init__(self, assignments, regions, services, stacks, status):
        self._assignments = assignments
        self._regions = regions
        self._services = services
        self._stacks = stacks
        self._status = status

        # TODO: shard scan for multiple schedulers
        self._segments = 1
        self._segment = 0

    def get_all_revision_weights(self):
        """Load services, revisions and weights"""
        services = {}
        rev_count = 0
        for service in self.services():
            name = service['service_name']

            service_revs = {k: int(v) for k, v in service.items()
                            if len(k) == REV_LENGTH}
            services[name] = service_revs
            rev_count += len(service_revs)

        logger.debug('Loaded %s services, %s revisions', len(services),
                     rev_count)
        return services

    def get_revision_weights(self, service_name):
        """Load revision weights for a particular service.
        :param service_name Service name.
        """
        try:
            service = self._services.get_item(service_name=service_name)
        except ItemNotFound:
            return {}
        return {k: int(v) for k, v in service.items() if len(k) == REV_LENGTH}

    def services(self):
        for service in self._services.scan(segment=self._segment,
                                           total_segments=self._segments):
            yield service

    def get_stacks(self):
        return [s for s in self._stacks.scan()]

    def set_stacks(self, stacks):
        if not stacks:
            return

        with self._stacks.batch_write() as batch:
            for stack in stacks:
                batch.put_item(stack)

    def set_assignment(self, service, machine, assignment):
        self._assignments.put_item(data={
            'service_name': service,
            'instance_id': machine,
            'assignment': assignment
        }, overwrite=True)

    def set_assignments(self, assignments):
        """Store assignments in a batch.
        :param assignments: Assignments to store.
        """
        with self._assignments.batch_write() as batch:
            for assignment in assignments:
                batch.put_item(assignment)

    def get_instance_assignments(self, service):
        """Get instances and assignments for a service
        :param service:  Service name.
        :return: Map of instances of assignments (None if unassigned).
        """
        live_instances = []
        dead_instances = []
        dead_cutoff = time.time() - INSTANCE_EXPIRY
        for instance_status in self._status.query_2(service__eq=service,
                                                    attributes=('instance_id',
                                                                'status_time')):
            instance_id = instance_status['instance_id']
            if instance_status['status_time'] < dead_cutoff:
                dead_instances.append(instance_id)
            else:
                live_instances.append(instance_id)

        if dead_instances:
            logger.debug('Removing %d dead instances.', len(dead_instances))
            with self._status.batch_write() as status_batch:
                for dead_instance in dead_instances:
                    status_batch.delete_item(service=service,
                                             instance_id=dead_instance)
            with self._assignments.batch_write() as assignment_batch:
                for dead_instance in dead_instances:
                    assignment_batch.delete_item(instance_id=dead_instance)

        assignments = defaultdict(list)
        if not live_instances:
            return assignments

        unassigned = set(live_instances)
        keys = [{'instance_id': i} for i in live_instances]
        for assignment in self._assignments.batch_get(keys=keys, attributes=(
                'instance_id', 'assignment')):
            assigned = assignment['assignment']
            instance_id = assignment['instance_id']
            unassigned.remove(instance_id)
            assignments[assigned].append(assignment)

        assignments[None] = [Item(self._assignments, data={
            'instance_id': instance_id,
            'service': service
        }) for instance_id in unassigned]

        return assignments

    def get_region_params(self, region):
        region_item = self._regions.get_item(region_name=region)
        return dict(region_item)
